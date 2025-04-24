#!/usr/bin/env python3
# Basic Blender test script to examine model rendering

import bpy
import os
import sys
import math
import traceback

# Clear the scene
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Get model path from command line argument
try:
    model_path = sys.argv[sys.argv.index('--') + 1]
except (ValueError, IndexError):
    model_path = "/Users/sannikov/Documents/GitHub/trajectory_generation_automation/models_raw/IKEA MARIUS STOOL.fbx"
    print(f"No model path provided, using default: {model_path}")

# Import model based on file extension
file_ext = os.path.splitext(model_path)[1].lower()
if file_ext == '.fbx':
    bpy.ops.import_scene.fbx(filepath=model_path)
elif file_ext == '.obj':
    bpy.ops.import_scene.obj(filepath=model_path)
elif file_ext == '.stl':
    bpy.ops.import_mesh.stl(filepath=model_path)
elif file_ext in ['.glb', '.gltf']:
    bpy.ops.import_scene.gltf(filepath=model_path)
elif file_ext in ['.step', '.stp']:
    bpy.ops.import_scene.step(filepath=model_path)
else:
    print(f"Unsupported file format: {file_ext}")
    sys.exit(1)

# Adjust camera and view to fit the model
bpy.ops.object.select_all(action='SELECT')
selection = bpy.context.selected_objects
if len(selection) == 0:
    print("No objects imported!")
    sys.exit(1)
    
# Calculate the center and size of the model
min_x, min_y, min_z = float('inf'), float('inf'), float('inf')
max_x, max_y, max_z = float('-inf'), float('-inf'), float('-inf')

for obj in selection:
    if obj.type == 'MESH':
        for v in obj.data.vertices:
            global_co = obj.matrix_world @ v.co
            min_x = min(min_x, global_co.x)
            min_y = min(min_y, global_co.y)
            min_z = min(min_z, global_co.z)
            max_x = max(max_x, global_co.x)
            max_y = max(max_y, global_co.y)
            max_z = max(max_z, global_co.z)

center_x = (min_x + max_x) / 2
center_y = (min_y + max_y) / 2
center_z = (min_z + max_z) / 2
size = max(max_x - min_x, max_y - min_y, max_z - min_z)

# For debugging
print(f"Model bounds: ({min_x:.2f}, {min_y:.2f}, {min_z:.2f}) to ({max_x:.2f}, {max_y:.2f}, {max_z:.2f})")
print(f"Model center: ({center_x:.2f}, {center_y:.2f}, {center_z:.2f})")
print(f"Model size: {size:.2f}")

# Create a simple material and assign to objects
material = bpy.data.materials.new(name="BasicMaterial")
material.use_nodes = True
nodes = material.node_tree.nodes
nodes["Principled BSDF"].inputs[0].default_value = (0.8, 0.6, 0.4, 1.0)  # Tan color

# Apply material to all objects
for obj in selection:
    if obj.type == 'MESH':
        if len(obj.data.materials) == 0:
            obj.data.materials.append(material)
        else:
            obj.data.materials[0] = material

# Set up lighting - key, fill, and back lights
# Key light (main light)
key_light = bpy.data.objects.new("KeyLight", bpy.data.lights.new("KeyLight", type='SUN'))
bpy.context.collection.objects.link(key_light)
key_light.location = (center_x + size, center_y + size, center_z + size)
key_light.rotation_euler = (math.radians(45), math.radians(45), 0)
key_light.data.energy = 5.0

# Fill light (softer light from opposite side)
fill_light = bpy.data.objects.new("FillLight", bpy.data.lights.new("FillLight", type='SUN'))
bpy.context.collection.objects.link(fill_light)
fill_light.location = (center_x - size, center_y + size, center_z + size/2)
fill_light.rotation_euler = (math.radians(30), math.radians(-45), 0)
fill_light.data.energy = 2.0

# Back light (rim light)
back_light = bpy.data.objects.new("BackLight", bpy.data.lights.new("BackLight", type='SUN'))
bpy.context.collection.objects.link(back_light)
back_light.location = (center_x, center_y - size, center_z + size)
back_light.rotation_euler = (math.radians(60), 0, 0)
back_light.data.energy = 3.0

# Set up camera to frame the model
camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
bpy.context.collection.objects.link(camera)

# Position camera to get a good view of the object
# Try isometric-ish view from front right
camera.location = (center_x + size*1.5, center_y - size*1.5, center_z + size)
camera.rotation_euler = (math.radians(60), 0, math.radians(45))

# Set the active camera
bpy.context.scene.camera = camera

# Adjust camera to fit the model
camera.data.lens = 35.0  # Set a standard lens length

# Create a world with a light color
world = bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg_node = world.node_tree.nodes["Background"]
bg_node.inputs[0].default_value = (0.9, 0.9, 0.9, 1.0)  # Light gray

# Set up rendering parameters
bpy.context.scene.render.image_settings.file_format = 'PNG'
bpy.context.scene.render.resolution_x = 1200
bpy.context.scene.render.resolution_y = 900
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.samples = 64
bpy.context.scene.render.filepath = "/Users/sannikov/Documents/GitHub/trajectory_generation_automation/build/img/test_render.png"

# Render the image
try:
    bpy.ops.render.render(write_still=True)
    print(f"Rendered test image to: {bpy.context.scene.render.filepath}")
except Exception as e:
    print(f"Error during rendering: {e}")
    traceback.print_exc()
