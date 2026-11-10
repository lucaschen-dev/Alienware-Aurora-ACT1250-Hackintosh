"""Small Metal compute and offscreen rendering checks; no third-party packages.

Run on macOS with Python 3. This validates arithmetic and texture readback, not
game performance or long-term driver stability. It writes no driver settings.
"""
import ctypes as C
import json

objc = C.CDLL('/usr/lib/libobjc.A.dylib')
C.CDLL('/System/Library/Frameworks/Foundation.framework/Foundation')
metal = C.CDLL('/System/Library/Frameworks/Metal.framework/Metal')
objc.objc_getClass.argtypes = [C.c_char_p]
objc.objc_getClass.restype = C.c_void_p
objc.sel_registerName.argtypes = [C.c_char_p]
objc.sel_registerName.restype = C.c_void_p
address = C.cast(objc.objc_msgSend, C.c_void_p).value


def call(obj, selector, result=C.c_void_p, args=(), values=()):
    if not obj:
        raise RuntimeError('Missing object for ' + selector)
    return C.CFUNCTYPE(result, C.c_void_p, C.c_void_p, *args)(address)(
        obj, objc.sel_registerName(selector.encode()), *values)


def cls(name):
    return objc.objc_getClass(name.encode())


def ns(string):
    return call(cls('NSString'), 'stringWithUTF8String:',
                args=(C.c_char_p,), values=(string.encode(),))


def string(obj):
    return call(obj, 'UTF8String', C.c_char_p).decode() if obj else ''


def error_text(obj):
    return string(call(obj, 'localizedDescription')) if obj else ''


class Size(C.Structure):
    _fields_ = [('width', C.c_size_t), ('height', C.c_size_t), ('depth', C.c_size_t)]


class Origin(C.Structure):
    _fields_ = [('x', C.c_size_t), ('y', C.c_size_t), ('z', C.c_size_t)]


class Region(C.Structure):
    _fields_ = [('origin', Origin), ('size', Size)]


def complete(command):
    call(command, 'commit', None)
    call(command, 'waitUntilCompleted', None)
    status = call(command, 'status', C.c_size_t)
    if status != 4:
        raise RuntimeError('Command status %s: %s' % (
            status, error_text(call(command, 'error'))))


pool = call(call(cls('NSAutoreleasePool'), 'alloc'), 'init')
metal.MTLCreateSystemDefaultDevice.restype = C.c_void_p
device = metal.MTLCreateSystemDefaultDevice()
if not device:
    raise RuntimeError('No Metal device')
queue = call(device, 'newCommandQueue')
source = '''#include <metal_stdlib>
using namespace metal;
kernel void check_compute(device float *out [[buffer(0)]],
                          uint i [[thread_position_in_grid]]) {
    out[i] = 3.0f * float(i) + 1.0f;
}
struct Vertex { float4 position [[position]]; };
vertex Vertex check_vertex(uint i [[vertex_id]]) {
    const float2 p[3] = {float2(-1,-1), float2(3,-1), float2(-1,3)};
    Vertex v; v.position = float4(p[i],0,1); return v;
}
fragment float4 check_fragment() { return float4(1.0f,0.25f,0.5f,1.0f); }
'''
error = C.c_void_p()
library = call(device, 'newLibraryWithSource:options:error:',
               args=(C.c_void_p, C.c_void_p, C.POINTER(C.c_void_p)),
               values=(ns(source), None, C.byref(error)))
if not library:
    raise RuntimeError('Compile: ' + error_text(error.value))


def function(name):
    return call(library, 'newFunctionWithName:', args=(C.c_void_p,), values=(ns(name),))


pipeline = call(device, 'newComputePipelineStateWithFunction:error:',
                args=(C.c_void_p, C.POINTER(C.c_void_p)),
                values=(function('check_compute'), C.byref(error)))
if not pipeline:
    raise RuntimeError('Compute pipeline: ' + error_text(error.value))
count = 4096
buffer = call(device, 'newBufferWithLength:options:',
              args=(C.c_size_t, C.c_size_t), values=(count * 4, 0))
command = call(queue, 'commandBuffer')
encoder = call(command, 'computeCommandEncoder')
call(encoder, 'setComputePipelineState:', None, args=(C.c_void_p,), values=(pipeline,))
call(encoder, 'setBuffer:offset:atIndex:', None,
     args=(C.c_void_p, C.c_size_t, C.c_size_t), values=(buffer, 0, 0))
threads = min(256, call(pipeline, 'maxTotalThreadsPerThreadgroup', C.c_size_t))
if not threads or count % threads:
    raise RuntimeError('Unexpected threadgroup limit')
call(encoder, 'dispatchThreadgroups:threadsPerThreadgroup:', None,
     args=(Size, Size), values=(Size(count // threads, 1, 1), Size(threads, 1, 1)))
call(encoder, 'endEncoding', None)
complete(command)
values = C.cast(call(buffer, 'contents'), C.POINTER(C.c_float))
bad = [i for i in range(count) if values[i] != 3 * i + 1]
if bad:
    raise RuntimeError('Compute mismatches: ' + str(bad[:10]))

# A fullscreen triangle must produce a uniform color, distinct from the default
# clear value, before every pixel is checked through a CPU readback.
width = height = 64
pixel_format = 70  # MTLPixelFormatRGBA8Unorm
descriptor = call(cls('MTLTextureDescriptor'),
                  'texture2DDescriptorWithPixelFormat:width:height:mipmapped:',
                  args=(C.c_size_t, C.c_size_t, C.c_size_t, C.c_bool),
                  values=(pixel_format, width, height, False))
call(descriptor, 'setUsage:', None, args=(C.c_size_t,), values=(4,))
call(descriptor, 'setStorageMode:', None, args=(C.c_size_t,), values=(0,))
texture = call(device, 'newTextureWithDescriptor:',
               args=(C.c_void_p,), values=(descriptor,))
render_descriptor = call(call(cls('MTLRenderPipelineDescriptor'), 'alloc'), 'init')
for selector, name in [('setVertexFunction:', 'check_vertex'),
                       ('setFragmentFunction:', 'check_fragment')]:
    call(render_descriptor, selector, None,
         args=(C.c_void_p,), values=(function(name),))
attachment = call(call(render_descriptor, 'colorAttachments'),
                  'objectAtIndexedSubscript:', args=(C.c_size_t,), values=(0,))
call(attachment, 'setPixelFormat:', None, args=(C.c_size_t,), values=(pixel_format,))
render_pipeline = call(device, 'newRenderPipelineStateWithDescriptor:error:',
                       args=(C.c_void_p, C.POINTER(C.c_void_p)),
                       values=(render_descriptor, C.byref(error)))
if not render_pipeline:
    raise RuntimeError('Render pipeline: ' + error_text(error.value))
render_pass = call(cls('MTLRenderPassDescriptor'), 'renderPassDescriptor')
attachment = call(call(render_pass, 'colorAttachments'),
                  'objectAtIndexedSubscript:', args=(C.c_size_t,), values=(0,))
call(attachment, 'setTexture:', None, args=(C.c_void_p,), values=(texture,))
call(attachment, 'setLoadAction:', None, args=(C.c_size_t,), values=(2,))
call(attachment, 'setStoreAction:', None, args=(C.c_size_t,), values=(1,))
command = call(queue, 'commandBuffer')
encoder = call(command, 'renderCommandEncoderWithDescriptor:',
               args=(C.c_void_p,), values=(render_pass,))
call(encoder, 'setRenderPipelineState:', None,
     args=(C.c_void_p,), values=(render_pipeline,))
call(encoder, 'drawPrimitives:vertexStart:vertexCount:', None,
     args=(C.c_size_t, C.c_size_t, C.c_size_t), values=(3, 0, 3))
call(encoder, 'endEncoding', None)
complete(command)
pixels = (C.c_ubyte * (width * height * 4))()
call(texture, 'getBytes:bytesPerRow:fromRegion:mipmapLevel:', None,
     args=(C.c_void_p, C.c_size_t, Region, C.c_size_t),
     values=(C.cast(pixels, C.c_void_p), width * 4,
             Region(Origin(0, 0, 0), Size(width, height, 1)), 0))
expected = (255, 64, 128, 255)
bad_pixels = []
for i in range(width * height):
    if any(abs(pixels[i * 4 + c] - expected[c]) > 1 for c in range(4)):
        bad_pixels.append(i)
if bad_pixels:
    raise RuntimeError('Render mismatches: %s; first pixel=%s' % (
        len(bad_pixels), list(pixels[:4])))
print(json.dumps({
    'device': string(call(device, 'name')),
    'compute': {'validation': 'passed', 'checkedElements': count,
                'formula': 'output[i] = 3 * i + 1', 'mismatches': len(bad)},
    'offscreenRender': {'validation': 'passed', 'width': width, 'height': height,
                        'checkedPixels': width * height, 'format': 'RGBA8Unorm',
                        'expectedRGBA': expected, 'firstPixelRGBA': list(pixels[:4]),
                        'tolerancePerChannel': 1, 'mismatches': len(bad_pixels)},
    'limitations': 'Basic functional checks only; no window presentation, game, sleep, or long stress test.'
}, indent=2))
call(pool, 'drain', None)
