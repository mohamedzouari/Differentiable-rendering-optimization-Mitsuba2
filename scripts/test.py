from objects_extractor import get_owners
from mask_generator import generate_masks
import enoki as ek
import mitsuba
import os
import json
mitsuba.set_variant('gpu_autodiff_rgb')
from mitsuba.core import Thread
from mitsuba.core.xml import load_file
from mitsuba.python.util import traverse

# Absolute or relative path to the XML file
filename = 'scenes/cboxwithdragon/cboxwithdragon.xml'

use_masks = True
base_path = 'results/EmitterSmall/'

if use_masks:
    base_path+='Masked/'
else:
    base_path+='Standard/'

    
dump_path = base_path+'iterations/'
try:
    os.makedirs(dump_path)
except:
    pass

diff_param_key = 'emitter.radiance.value'
diff_param_owner = 'emitter'



# Add the scene directory to the FileResolver's search path
Thread.thread().file_resolver().append(os.path.dirname(filename))

# Load the scene
scene = load_file(filename)

# Find differentiable scene parameters
params = traverse(scene)
params.keep([diff_param_key])

owners = get_owners(params, scene)
masks = generate_masks(owners, scene)

from mitsuba.core import Color3f
diff_param_ref = Color3f(params[diff_param_key])
#light_ref = Color3f(params['light.reflectance.value'])

# Render a reference image (no derivatives used yet)
from mitsuba.python.autodiff import render, write_bitmap
image_ref = render(scene, spp=8)
crop_size = scene.sensors()[0].film().crop_size()
write_bitmap(base_path+'reference.png', image_ref, crop_size)
#write_bitmap('renders/mask.png', masks['green'], crop_size)


# Change the left wall into a bright white surface
params[diff_param_key] = [1.0,0.1,0.1]
params.update()

# Construct an Adam optimizer that will adjust the parameters 'params'
from mitsuba.python.autodiff import SGD
opt = SGD(params, lr=.2, momentum=0.9)

mask_len = ek.hsum(masks[diff_param_owner])[0]
errors = list()
converged = False
it = 0
while converged != True and it <= 100:
    # Perform a differentiable rendering of the scene
    image = render(scene, optimizer=opt, unbiased=True, spp=1)

    write_bitmap(dump_path + 'out_%03i.png' % it, image, crop_size)

    # Objective: MSE between 'image' and 'image_ref'
    #ob_val = ek.hsum(ek.sqr(image - image_ref)) / len(image)
    if use_masks:
        ob_val = ek.hsum( masks[diff_param_owner] * ek.sqr(image - image_ref)) / mask_len
    else:
        ob_val = ek.hsum(ek.sqr(image - image_ref)) / len(image)

    # Back-propagate errors to input parameters
    ek.backward(ob_val)

    # Optimizer: take a gradient step
    opt.step()

    err_ref = ek.hsum(ek.sqr(diff_param_ref - params[diff_param_key]))
    #if err_ref[0] < 0.0001:
        #converged = True
    errors.append(err_ref[0])
    print('Iteration %03i : error= %g' % (it, err_ref[0]))
    it+=1

f = open(base_path+'Errors.txt', 'w')
json.dump(errors, f, indent=2)
f.close()
