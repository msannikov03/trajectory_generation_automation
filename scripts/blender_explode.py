#!/usr/bin/env python3

import os
import sys
import json
import re
import math
import logging
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Special import handling for bpy and mathutils
try:
    import bpy
    import mathutils
    INSIDE_BLENDER = True
except ImportError:
    INSIDE_BLENDER = False
    # Mocks are disabled/commented out as they caused SyntaxErrors when parsed by Blender's Python
    # and are less necessary now that stubs (like fake-bpy-module) are installed for external editors.
    # If you need mocks for basic linting WITHOUT stubs, carefully review/simplify them.
    logging.warning("bpy/mathutils modules not available outside Blender.")
    # --- Mock Definitions (DISABLED / Minimal) ---
    class MockVec:
        def __init__(self, v=(0,0,0)): self.v = list(v) # Use list for mutability if needed
        def __add__(self, o): return MockVec([a+b for a,b in zip(self.v, o.v)]) if isinstance(o, MockVec) else self
        def __sub__(self, o): return MockVec([a-b for a,b in zip(self.v, o.v)]) if isinstance(o, MockVec) else self
        def __mul__(self, scalar): return MockVec([a*scalar for a in self.v])
        def __truediv__(self, scalar): return MockVec([a/scalar for a in self.v]) if scalar != 0 else self
        @property
        def length(self): return math.sqrt(sum(a*a for a in self.v))
        def normalized(self): l=self.length; return self / l if l > 1e-6 else MockVec()
        def angle(self, o): return 0.0 # Simplified
        def cross(self, o): return MockVec() # Simplified
        def copy(self): return MockVec(self.v)
        def to_track_quat(self, *a): return MockQuat()
        @property
        def x(self): return self.v[0]
        @property
        def y(self): return self.v[1]
        @property
        def z(self): return self.v[2]
        @x.setter
        def x(self, v): self.v[0] = v
        @y.setter
        def y(self, v): self.v[1] = v
        @z.setter
        def z(self, v): self.v[2] = v
    class MockQuat:
        def to_euler(self): return (0,0,0)
    if 'mathutils' not in sys.modules:
        class MockMathUtilsMod:
            Vector = MockVec
            Quaternion = MockQuat
        mathutils = MockMathUtilsMod()
    # Minimal bpy placeholder if needed by linter
    if 'bpy' not in sys.modules:
         class BpyPlaceHolder: pass
         bpy = BpyPlaceHolder()
    # --- End Mock Definitions ---


# --- Configuration ---
RENDER_ENGINE = 'CYCLES' # 'CYCLES' for quality, 'BLENDER_EEVEE' for speed
CYCLES_SAMPLES = 128 # Increase for less noise, decrease for speed
RESOLUTION_X = 1200
RESOLUTION_Y = 900
BACKGROUND_COLOR = (1.0, 1.0, 1.0, 1.0) # White background
PART_COLORS = {
    "leg":   (1.0, 0.2, 0.0, 1.0), # Vivid orange-red
    "seat":  (0.0, 0.4, 1.0, 1.0), # Vibrant blue
    "beam":  (1.0, 0.9, 0.0, 1.0), # Bright yellow
    "screw": (0.2, 0.2, 0.2, 1.0), # Dark Gray
    "part":  (0.0, 0.8, 0.2, 1.0)  # Bright green
}
ARROW_COLOR = (1.0, 0.0, 0.0, 1.0) # Bright Red
# *** ADJUSTED Arrow Emission Strength Significantly ***
ARROW_EMISSION_STRENGTH = 15.0
# Arrow size relative to the part it's pointing to (adjust as needed)
ARROW_THICKNESS_RATIO = 0.05 # Thickness relative to part's average dimension
ARROW_HEAD_SIZE_RATIO = 0.15 # Head size relative to part's average dimension
ARROW_MIN_THICKNESS = 0.02
ARROW_MAX_THICKNESS = 0.15
ARROW_MIN_HEAD_SIZE = 0.06
ARROW_MAX_HEAD_SIZE = 0.4
ARROW_MIN_LENGTH_FACTOR = 0.5 # Arrow shaft will be at least this factor times the part's size

# Explode factor - controls distance. Lower value = closer parts.
EXPLODE_FACTOR = 0.8
# Maximum distance a part will be exploded away from its origin
MAX_EXPLODE_DISTANCE = 10.0
# How many parts to assemble per step (approx)
TARGET_STEPS = 6 # Aim for roughly this many steps

# Lighting setup
LIGHTS_CONFIG = [
    {'type': 'SUN', 'location': (5, 5, 10), 'rotation': (math.radians(45), math.radians(30), 0), 'energy': 3.0, 'angle': 0.1}, # Key light
    {'type': 'POINT', 'location': (-5, 5, 5), 'rotation': (0, 0, 0), 'energy': 50.0, 'shadow_soft_size': 2.0}, # Fill light
    {'type': 'SPOT', 'location': (0, -10, 7), 'rotation': (math.radians(110), 0, 0), 'energy': 30.0, 'spot_size': math.radians(70), 'shadow_soft_size': 1.5} # Back light
]

# Camera settings
CAMERA_LENS = 50 # mm, 50mm is standard, lower is wider angle
# *** ADJUSTED Camera Distance Factor for closer view ***
CAMERA_DISTANCE_FACTOR = 1.5

# --- End Configuration ---

# Get command line arguments
# Check if running inside Blender before accessing bpy-dependent things
if INSIDE_BLENDER:
    try:
        argv = sys.argv
        # Ensure '--' exists before trying to split
        if '--' in argv:
             argv = argv[argv.index("--") + 1:]
             if argv: # Check if list is not empty after split
                 model_path = argv[0]
             else:
                 logging.error("No arguments provided after '--'.")
                 model_path = None
        else:
             # Allow running script directly in Blender UI without args for testing
             logging.warning("Script run without '--' separator. Model path argument required for background mode.")
             # Attempt to get path from command line if no '--' was used (less reliable)
             if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
                  model_path = sys.argv[1]
                  logging.warning(f"Assuming model path from first argument: {model_path}")
             else:
                  model_path = None # No model path provided

    except Exception as e:
        logging.error(f"Error parsing arguments: {e}")
        model_path = None
else:
    # Handle case where script is run outside Blender (e.g., for linting)
    # Set default values or expect errors if bpy is accessed
    model_path = "path/to/default_model_for_linting.fbx" # Example placeholder
    logging.warning("Running outside Blender. Using placeholder model path.")


# Project paths (ensure model_path is valid before using it)
if model_path and os.path.exists(model_path):
    try:
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        MODEL_NAME = os.path.splitext(os.path.basename(model_path))[0]
        OUTPUT_DIR = os.path.join(BASE_DIR, 'build', 'img', MODEL_NAME)
        METADATA_FILE = os.path.join(OUTPUT_DIR, 'metadata.json')
    except Exception as e:
        logging.error(f"Error setting up paths: {e}")
        # Decide how to handle this - maybe exit if essential paths fail
        MODEL_NAME = "unknown_model" # Placeholder
        OUTPUT_DIR = os.path.join(os.getcwd(), 'build', 'img', MODEL_NAME) # Default output
        METADATA_FILE = os.path.join(OUTPUT_DIR, 'metadata.json')
        if INSIDE_BLENDER: # Only exit if running inside Blender and paths fail
             logging.error("Exiting due to path setup error inside Blender.")
             sys.exit(1)

elif INSIDE_BLENDER: # If model_path is None or invalid *inside* Blender, exit
     logging.error(f"Invalid or missing model path provided: {model_path}. Exiting.")
     sys.exit(1)
else: # If outside Blender, set placeholders
    logging.warning("Model path missing or invalid outside Blender. Using placeholders.")
    MODEL_NAME = "unknown_model"
    OUTPUT_DIR = os.path.join(os.getcwd(), 'build', 'img', MODEL_NAME)
    METADATA_FILE = os.path.join(OUTPUT_DIR, 'metadata.json')


# --- Helper Functions ---
# These functions now assume they are ONLY called when INSIDE_BLENDER is True
# or they handle the case where bpy is not available gracefully.

def clear_scene():
    """Removes all objects, materials, etc. from the current scene."""
    if not INSIDE_BLENDER: return
    try:
        # Ensure not in edit mode before clearing
        if bpy.context.object and bpy.context.object.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # More robust clearing
        for obj in list(bpy.data.objects): # Use list copy for safe removal
            bpy.data.objects.remove(obj, do_unlink=True)
        for collection in list(bpy.data.collections):
            # Don't remove the master scene collection if it exists
            if collection != bpy.context.scene.collection:
                # Unlink objects first (might be redundant with obj removal)
                for obj in list(collection.objects):
                    collection.objects.unlink(obj)
                bpy.data.collections.remove(collection)
        for material in list(bpy.data.materials):
            bpy.data.materials.remove(material)
        for mesh in list(bpy.data.meshes):
             bpy.data.meshes.remove(mesh)
        for world in list(bpy.data.worlds):
            bpy.data.worlds.remove(world)
        for light in list(bpy.data.lights):
             bpy.data.lights.remove(light)
        for cam in list(bpy.data.cameras):
             bpy.data.cameras.remove(cam)

        # Ensure a default world exists after clearing
        if bpy.context.scene.world is None:
             bpy.context.scene.world = bpy.data.worlds.new("World")

        logging.info("Scene cleared.")
    except Exception as e:
        logging.error(f"Error clearing scene: {e}\n{traceback.format_exc()}")


def import_model(filepath):
    """Imports a model based on its file extension."""
    if not INSIDE_BLENDER: return False
    ext = os.path.splitext(filepath)[1].lower()
    logging.info(f"Importing model: {filepath} (type: {ext})")
    try:
        if ext == '.fbx':
            # Optional FBX settings: use_manual_orientation=True, axis_forward='-Z', axis_up='Y' etc.
            bpy.ops.import_scene.fbx(filepath=filepath)
        elif ext == '.glb' or ext == '.gltf':
            bpy.ops.import_scene.gltf(filepath=filepath)
        elif ext == '.stl':
            bpy.ops.import_mesh.stl(filepath=filepath)
        elif ext == '.obj':
            # Optional OBJ settings: axis_forward='-Z', axis_up='Y'
            bpy.ops.import_scene.obj(filepath=filepath)
        elif ext == '.step' or ext == '.stp':
            # Requires the STEP importer addon to be enabled in Blender
            if 'io_scene_step' not in bpy.context.preferences.addons:
                 logging.error("STEP import requires the 'io_scene_step' addon to be enabled in Blender preferences.")
                 raise ImportError("STEP importer addon not enabled")
            bpy.ops.import_scene.step(filepath=filepath)
        else:
            logging.error(f"Unsupported file format: {ext}")
            return False
        logging.info("Model imported successfully.")
        return True
    except Exception as e:
        logging.error(f"Failed to import model {filepath}: {e}\n{traceback.format_exc()}")
        return False

def separate_and_get_parts():
    """Separates imported objects into loose parts and returns them."""
    if not INSIDE_BLENDER: return []
    initial_objects = list(bpy.context.scene.objects)
    parts = []
    processed_original_objects = set() # Track originals to avoid re-processing instances

    logging.info(f"Attempting to separate {len(initial_objects)} initial objects.")

    # Ensure we are in Object mode
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
         bpy.ops.object.mode_set(mode='OBJECT')

    for obj in initial_objects:
        if obj in processed_original_objects:
            continue # Skip if we already processed this original object

        if obj.type == 'MESH':
            logging.info(f"Processing mesh object: {obj.name}")
            processed_original_objects.add(obj)
            # Ensure the object is selected and active
            try:
                bpy.ops.object.select_all(action='DESELECT')
                obj.select_set(True)
                bpy.context.view_layer.objects.active = obj
            except Exception as select_e:
                 logging.error(f"Could not select/activate object {obj.name}: {select_e}")
                 continue # Skip this object if selection fails

            try:
                # Apply transformations before separating
                bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

                # Separate by loose parts in Edit Mode
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.separate(type='LOOSE')
                bpy.ops.object.mode_set(mode='OBJECT')

                # Newly created objects are selected
                newly_separated = [o for o in bpy.context.selected_objects if o.type == 'MESH']

                if len(newly_separated) > 0:
                    # If separation occurred, add the new parts
                    logging.info(f"Separated '{obj.name}' into {len(newly_separated)} part(s).")
                    parts.extend(newly_separated)
                    # Original object might be empty/redundant now, optionally remove it
                    # Check if original obj still has geometry
                    # if obj.data and not obj.data.vertices:
                    #     logging.info(f"Removing original empty container: {obj.name}")
                    #     bpy.data.objects.remove(obj, do_unlink=True)
                else:
                    # If separation didn't yield *new* objects (maybe it was already separate)
                    logging.info(f"No new loose parts created for '{obj.name}', keeping it.")
                    parts.append(obj) # Keep the original object

            except RuntimeError as e: # Catch specific Blender errors
                 logging.warning(f"Runtime error separating object '{obj.name}': {e}. Keeping original.")
                 if obj not in parts: parts.append(obj)
                 # Ensure back in object mode
                 if bpy.context.object and bpy.context.object.mode == 'EDIT':
                      bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as e:
                 logging.error(f"Unexpected error separating '{obj.name}': {e}\n{traceback.format_exc()}. Keeping original.")
                 if obj not in parts: parts.append(obj)
                 if bpy.context.object and bpy.context.object.mode == 'EDIT':
                      bpy.ops.object.mode_set(mode='OBJECT')


        elif obj.type != 'MESH':
            logging.info(f"Skipping non-mesh object: {obj.name} (type: {obj.type})")
            processed_original_objects.add(obj) # Mark as processed to avoid re-check


    if not parts:
        logging.warning("No mesh parts found after separation attempt. Using initial mesh objects.")
        parts = [o for o in initial_objects if o.type == 'MESH']

    if not parts:
         logging.error("CRITICAL: No mesh parts could be identified in the model.")
         return []

    # Final cleanup: Remove any None or invalid objects from the list
    parts = [p for p in parts if p and p.name in bpy.data.objects]

    logging.info(f"Total valid parts identified: {len(parts)}")
    # Sort parts roughly by Z position (bottom to top) - helps with assembly order guess
    try:
        parts.sort(key=lambda obj: obj.location.z)
    except Exception as e:
        logging.warning(f"Could not sort parts by Z location: {e}")

    return parts


def create_material(name, color):
    """Creates a Blender material with matte settings."""
    if not INSIDE_BLENDER: return None
    try:
        material = bpy.data.materials.new(name=name)
        material.use_nodes = True
        # Get node tree safely
        node_tree = material.node_tree
        if not node_tree: raise ValueError("Material has no node tree.")
        # Get BSDF node safely
        bsdf = node_tree.nodes.get("Principled BSDF")
        if not bsdf: # If it doesn't exist, try adding one
             bsdf = node_tree.nodes.new(type='ShaderNodeBsdfPrincipled')
             # Link it to output if possible
             output_node = node_tree.nodes.get("Material Output")
             if output_node:
                 node_tree.links.new(bsdf.outputs['BSDF'], output_node.inputs['Surface'])

        if not bsdf: raise ValueError("Could not get or create Principled BSDF node.")

        # Access inputs safely
        bsdf.inputs['Base Color'].default_value = color
        bsdf.inputs['Metallic'].default_value = 0.05
        bsdf.inputs['Specular'].default_value = 0.1
        bsdf.inputs['Roughness'].default_value = 0.85
        return material
    except Exception as e:
        logging.error(f"Failed to create material '{name}': {e}\n{traceback.format_exc()}")
        return None

def create_emissive_material(name, color, strength):
    """Creates a Blender material that glows."""
    if not INSIDE_BLENDER: return None
    try:
        material = bpy.data.materials.new(name=name)
        material.use_nodes = True
        # Get node tree safely
        node_tree = material.node_tree
        if not node_tree: raise ValueError("Material has no node tree.")
        # Get BSDF node safely
        bsdf = node_tree.nodes.get("Principled BSDF")
        if not bsdf: # If it doesn't exist, try adding one
             bsdf = node_tree.nodes.new(type='ShaderNodeBsdfPrincipled')
             output_node = node_tree.nodes.get("Material Output")
             if output_node:
                 node_tree.links.new(bsdf.outputs['BSDF'], output_node.inputs['Surface'])

        if not bsdf: raise ValueError("Could not get or create Principled BSDF node.")

        # Set base color slightly darker so emission is primary effect
        darker_color = [c * 0.8 for c in color[:3]]
        darker_color.append(color[3]) # Keep alpha
        bsdf.inputs['Base Color'].default_value = darker_color
        bsdf.inputs['Metallic'].default_value = 0.0
        bsdf.inputs['Specular'].default_value = 0.0
        bsdf.inputs['Roughness'].default_value = 0.9
        # Emission color input takes RGB (first 3 of RGBA)
        bsdf.inputs['Emission Color'].default_value = color[:3]
        bsdf.inputs['Emission Strength'].default_value = strength
        return material
    except Exception as e:
        logging.error(f"Failed to create emissive material '{name}': {e}\n{traceback.format_exc()}")
        return None

def get_object_size(obj):
    """Returns the approximate average dimension of an object's bounding box."""
    if not obj or not hasattr(obj, 'dimensions'):
        return 1.0 # Default size if object is invalid
    dims = obj.dimensions
    # Handle cases where dimensions might be zero if object is flat/degenerate
    valid_dims = [d for d in dims if d > 1e-6]
    if not valid_dims: return 1e-6 # Return tiny size if all dims are zero
    return sum(valid_dims) / len(valid_dims)


def create_arrow(start, end, target_part, name="Arrow"):
    """Creates a 3D arrow pointing from start to end, scaled relative to target_part."""
    if not INSIDE_BLENDER: return None
    # --- Log Entry Point ---
    logging.info(f"Attempting to create arrow: '{name}'") # ADDED Log
    shaft = None # Initialize variables
    head = None
    arrow = None
    try:
        direction = end - start
        height = direction.length

        # --- Logging ---
        logging.info(f"Arrow '{name}': Start=({start.x:.2f},{start.y:.2f},{start.z:.2f}), End=({end.x:.2f},{end.y:.2f},{end.z:.2f}), Height={height:.4f}")

        if height < 0.01: # Avoid zero-length arrows
            logging.warning(f"Arrow '{name}' has near-zero length ({height:.4f}). Skipping.")
            return None

        part_size = get_object_size(target_part)
        min_arrow_length = part_size * ARROW_MIN_LENGTH_FACTOR

        # Ensure arrow isn't disproportionately small compared to the part
        if height < min_arrow_length:
             logging.info(f"Arrow '{name}' height {height:.4f} < min_length {min_arrow_length:.4f}. Adjusting.")
             # Adjust end point to maintain direction but ensure minimum length
             if direction.length > 1e-6:
                 normalized_direction = direction.normalized()
                 end = start + normalized_direction * height
                 direction = end - start # Recalculate direction vector
                 height = direction.length # Update height
             else:
                 logging.warning(f"Arrow '{name}' original direction was zero. Cannot create arrow.")
                 return None

        # Calculate dynamic thickness and head size based on part size
        thickness = max(ARROW_MIN_THICKNESS, min(ARROW_MAX_THICKNESS, part_size * ARROW_THICKNESS_RATIO))
        head_size = max(ARROW_MIN_HEAD_SIZE, min(ARROW_MAX_HEAD_SIZE, part_size * ARROW_HEAD_SIZE_RATIO))

        # Ensure head is not larger than shaft is long (visually looks bad)
        head_depth = height * 0.3
        head_size = min(head_size, head_depth * 1.5) # Cap head radius relative to its depth

        # --- Log before creating primitives ---
        logging.info(f"Arrow '{name}': Creating primitives (H:{height:.2f}, T:{thickness:.3f}, HS:{head_size:.3f})") # ADDED Log
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=12,
            radius=thickness,
            depth=height * 0.75, # Shaft is 75% of total length
            location=start + direction * (height * 0.375) # Position center of shaft
        )
        shaft = bpy.context.active_object; shaft.name = f"{name}_shaft"; logging.info(f"Arrow '{name}': Shaft created.") # ADDED Log
        bpy.ops.mesh.primitive_cone_add(
            vertices=16,
            radius1=head_size,
            radius2=0,
            depth=head_depth, # Head is 30% of total length
            location=start + direction * (height * 0.85) # Position base of cone
        )
        head = bpy.context.active_object; head.name = f"{name}_head"; logging.info(f"Arrow '{name}': Head created.") # ADDED Log

        # --- Log before alignment ---
        logging.info(f"Arrow '{name}': Aligning...") # ADDED Log
        z_axis = mathutils.Vector((0, 0, 1))
        # Ensure direction is normalized for accurate angle calculation
        dir_normalized = direction.normalized()
        if dir_normalized.length < 1e-6: # Avoid issues with zero vectors
             logging.warning(f"Arrow '{name}' direction is zero vector. Skipping rotation.")
        else:
            angle = dir_normalized.angle(z_axis)
            axis = z_axis.cross(dir_normalized)

            if axis.length > 0.01: # Check for valid rotation axis
                 quat = mathutils.Quaternion(axis, angle)
                 shaft.rotation_euler = quat.to_euler()
                 head.rotation_euler = quat.to_euler()
            elif abs(angle - math.pi) < 1e-4: # Handle pointing straight down (parallel to Z, angle is pi)
                 shaft.rotation_euler = (math.pi, 0, 0)
                 head.rotation_euler = (math.pi, 0, 0)
            # else: pointing straight up, angle is ~0, no rotation needed
        logging.info(f"Arrow '{name}': Alignment done.") # ADDED Log

        # --- Log before material assignment ---
        logging.info(f"Arrow '{name}': Assigning material...") # ADDED Log
        arrow_mat = create_emissive_material(f"{name}_material", ARROW_COLOR, ARROW_EMISSION_STRENGTH)
        if arrow_mat:
            # Check if mesh data exists before appending
            if shaft.data:
                 shaft.data.materials.append(arrow_mat)
            else:
                 logging.warning(f"Arrow shaft '{shaft.name}' has no mesh data to assign material.")
            if head.data:
                 head.data.materials.append(arrow_mat)
            else:
                 logging.warning(f"Arrow head '{head.name}' has no mesh data to assign material.")
            logging.info(f"Arrow '{name}': Material assigned.") # ADDED Log
        else:
            logging.error(f"Failed to create material for arrow '{name}'")


        # --- Log before join ---
        logging.info(f"Arrow '{name}': Joining parts...") # ADDED Log
        bpy.ops.object.select_all(action='DESELECT')
        shaft.select_set(True)
        head.select_set(True)
        bpy.context.view_layer.objects.active = shaft
        bpy.ops.object.join()
        arrow = bpy.context.active_object # The joined object
        arrow.name = name
        logging.info(f"Created arrow '{name}' SUCCESSFULLY (L={height:.2f}, T={thickness:.3f}, H={head_size:.3f})") # Final success log
        return arrow

    except Exception as e:
        logging.error(f"Failed during arrow creation '{name}': {e}\n{traceback.format_exc()}")
        # Clean up primitives if they exist and are valid Blender objects
        try:
            if shaft and shaft.name in bpy.data.objects: bpy.data.objects.remove(shaft, do_unlink=True)
            if head and head.name in bpy.data.objects: bpy.data.objects.remove(head, do_unlink=True)
            # If join succeeded but error happened later, remove joined object
            if arrow and arrow.name in bpy.data.objects: bpy.data.objects.remove(arrow, do_unlink=True)
        except Exception as cleanup_e:
             logging.error(f"Error during arrow cleanup: {cleanup_e}")
        return None # Ensure None is returned on error


def setup_scene():
    """Sets up lighting, camera, and rendering parameters."""
    if not INSIDE_BLENDER: return
    logging.info("Setting up scene (lights, camera, render settings)...")
    try:
        # Lighting
        for i, config in enumerate(LIGHTS_CONFIG):
            bpy.ops.object.light_add(type=config['type'])
            light_obj = bpy.context.active_object
            light_obj.name = f"{config['type']}_Light_{i}"
            light_obj.location = config['location']
            light_obj.rotation_euler = config['rotation']
            light_data = light_obj.data
            light_data.energy = config.get('energy', 1.0)
            if config['type'] == 'SUN':
                if hasattr(light_data, 'angle'): light_data.angle = config.get('angle', 0.1)
            elif config['type'] == 'SPOT':
                if hasattr(light_data, 'spot_size'): light_data.spot_size = config.get('spot_size', math.radians(45))
                # Ensure shadow_soft_size exists for SPOT before setting
                if hasattr(light_data, 'shadow_soft_size'):
                    light_data.shadow_soft_size = config.get('shadow_soft_size', 0.5)
            elif config['type'] == 'POINT':
                 if hasattr(light_data, 'shadow_soft_size'):
                    light_data.shadow_soft_size = config.get('shadow_soft_size', 0.5)

        # Camera
        bpy.ops.object.camera_add()
        camera = bpy.context.active_object
        camera.name = "SceneCamera"
        camera.data.lens = CAMERA_LENS
        bpy.context.scene.camera = camera # Set as active camera

        # World Background
        # Ensure a world exists
        if bpy.context.scene.world is None:
             bpy.context.scene.world = bpy.data.worlds.new("World")
        world = bpy.context.scene.world
        world.use_nodes = True
        node_tree = world.node_tree
        if not node_tree: # Should have tree if use_nodes is True, but check anyway
            logging.error("World has no node tree after enabling nodes.")
        else:
            bg_node = node_tree.nodes.get("Background")
            if not bg_node:
                # Find or create output node
                output_node = node_tree.nodes.get("World Output")
                if not output_node:
                    output_node = node_tree.nodes.new(type='ShaderNodeOutputWorld')
                # Create and link background node
                bg_node = node_tree.nodes.new(type='ShaderNodeBackground')
                if output_node:
                    node_tree.links.new(bg_node.outputs['Background'], output_node.inputs['Surface'])
                else:
                    logging.warning("Could not find or create World Output node.")

            if bg_node:
                # Access inputs safely by name
                color_input = bg_node.inputs.get('Color')
                strength_input = bg_node.inputs.get('Strength')
                if color_input: color_input.default_value = BACKGROUND_COLOR
                if strength_input: strength_input.default_value = 1.0
            else:
                 logging.warning("Could not find or create Background node in world shader tree.")


        # Render Settings
        render = bpy.context.scene.render
        render.engine = RENDER_ENGINE
        render.resolution_x = RESOLUTION_X
        render.resolution_y = RESOLUTION_Y
        render.image_settings.file_format = 'PNG'
        render.image_settings.color_mode = 'RGBA' # Ensure alpha channel if needed later
        render.film_transparent = False # Use solid background

        if RENDER_ENGINE == 'CYCLES':
            cycles = bpy.context.scene.cycles
            cycles.samples = CYCLES_SAMPLES
            # Optional: Use GPU if available
            try:
                prefs = bpy.context.preferences.addons['cycles'].preferences
                prefs.refresh_devices() # Refresh device list
                devices = prefs.get_devices()
                # Filter devices based on type (CUDA, OPTIX, HIP, METAL, ONEAPI)
                gpu_devices = [d for d_list in devices for d in d_list if d.type != 'CPU']

                if gpu_devices:
                    # Set Cycles preferences to use GPU devices
                    prefs.compute_device_type = gpu_devices[0].type # Or loop to set specific type
                    bpy.context.scene.cycles.device = 'GPU'
                    # Enable the devices
                    prefs.set_devices_usage(use_cpu=False, use_gpu=True)
                    logging.info(f"Set Cycles compute device to GPU ({[d.name for d in gpu_devices]})")
                else:
                     bpy.context.scene.cycles.device = 'CPU'
                     prefs.set_devices_usage(use_cpu=True, use_gpu=False)
                     logging.info("No compatible GPU found or enabled for Cycles. Using CPU.")
            except Exception as gpu_e:
                logging.warning(f"Could not configure GPU rendering: {gpu_e}. Using CPU.")
                bpy.context.scene.cycles.device = 'CPU'


        elif RENDER_ENGINE == 'BLENDER_EEVEE':
            eevee = bpy.context.scene.eevee
            eevee.taa_render_samples = 64 # Adjust Eevee samples
            eevee.use_ssr = True # Screen space reflections
            eevee.use_bloom = True


        logging.info("Scene setup complete.")
    except Exception as e:
        logging.error(f"Error during scene setup: {e}\n{traceback.format_exc()}")


def look_at(obj, target):
    """Points the object's -Z axis towards the target."""
    if not INSIDE_BLENDER: return
    try:
        direction = target - obj.location
        # Avoid issues with zero vector or object at target
        if direction.length < 1e-6:
             return
        # point the obj's '-Z' and use its 'Y' as up
        rot_quat = direction.to_track_quat('-Z', 'Y')
        obj.rotation_euler = rot_quat.to_euler()
    except Exception as e:
        logging.warning(f"Failed to execute look_at for '{obj.name}': {e}")


def frame_objects(target_objects):
    """Positions the camera to frame the target_objects."""
    if not INSIDE_BLENDER: return
    # Filter out any None objects just in case
    valid_targets = [obj for obj in target_objects if obj and obj.name in bpy.data.objects] # Ensure obj exists
    if not valid_targets:
        logging.warning("frame_objects called with no valid target objects.")
        return
    if not bpy.context.scene.camera:
         logging.error("No active camera found for framing.")
         return

    camera = bpy.context.scene.camera
    min_coord = mathutils.Vector((float('inf'), float('inf'), float('inf')))
    max_coord = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))
    valid_bounds_found = False

    for obj in valid_targets:
        # Convert bounds to world space
        if hasattr(obj, 'bound_box') and hasattr(obj, 'matrix_world'):
             try:
                 # Check if bound_box is valid (can be None for some object types like Empty)
                 # Also check if object is visible in viewport, hidden objects can have invalid bounds sometimes
                 if obj.bound_box is None or obj.hide_viewport: continue
                 world_bbox_corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
                 for corner in world_bbox_corners:
                      min_coord.x = min(min_coord.x, corner.x)
                      min_coord.y = min(min_coord.y, corner.y)
                      min_coord.z = min(min_coord.z, corner.z)
                      max_coord.x = max(max_coord.x, corner.x)
                      max_coord.y = max(max_coord.y, corner.y)
                      max_coord.z = max(max_coord.z, corner.z)
                 valid_bounds_found = True # Found at least one object with bounds
             except TypeError as te: # Catch potential errors with obj.bound_box
                  logging.warning(f"TypeError getting bounds for object '{obj.name}' (type: {obj.type}): {te}")
             except Exception as bound_e:
                  logging.warning(f"Could not get bounds for object '{obj.name}': {bound_e}")
        elif obj.type == 'EMPTY' and hasattr(obj, 'empty_display_size') and not obj.hide_viewport:
             # Use empty size and location for bounds
             s = obj.empty_display_size * 0.5 # Use half size for extent
             loc = obj.matrix_world.translation
             min_coord.x, min_coord.y, min_coord.z = min(min_coord.x, loc.x-s), min(min_coord.y, loc.y-s), min(min_coord.z, loc.z-s)
             max_coord.x, max_coord.y, max_coord.z = max(max_coord.x, loc.x+s), max(max_coord.y, loc.y+s), max(max_coord.z, loc.z+s)
             valid_bounds_found = True
        elif obj.type in {'LIGHT', 'CAMERA'} and not obj.hide_viewport:
             # Include lights/cameras at their location for framing if needed
             pos = obj.matrix_world.translation
             min_coord.x, min_coord.y, min_coord.z = min(min_coord.x, pos.x), min(min_coord.y, pos.y), min(min_coord.z, pos.z)
             max_coord.x, max_coord.y, max_coord.z = max(max_coord.x, pos.x), max(max_coord.y, pos.y), max(max_coord.z, pos.z)
             valid_bounds_found = True # Consider its position as part of bounds


    if not valid_bounds_found:
        logging.warning("Could not determine valid bounds for framing any target object.")
        # Default position if bounds fail completely
        center = mathutils.Vector((0, 0, 0))
        size = 5.0
    else:
        center = (min_coord + max_coord) / 2.0
        # Calculate size based on diagonal of bounding box for better scaling
        size = (max_coord - min_coord).length
        size = max(size, 0.5) # Ensure min size


    # Position camera based on calculated center and size
    distance = size * CAMERA_DISTANCE_FACTOR # Uses updated factor
    # Consistent viewing angle (e.g., front-right-top)
    camera_offset = mathutils.Vector((0.8, -0.8, 0.6)).normalized() * distance # Adjusted angle slightly
    camera.location = center + camera_offset

    # Point camera at the center
    look_at(camera, center)
    logging.info(f"Framed objects. Center:({center.x:.2f},{center.y:.2f},{center.z:.2f}), Size:{size:.2f}, CamDist:{distance:.2f}")


def render_image(filepath_no_ext):
    """Renders the current scene and saves to the specified path (without extension)."""
    if not INSIDE_BLENDER: return
    try:
        full_path = f"{filepath_no_ext}.png"
        # Ensure directory exists before rendering
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        bpy.context.scene.render.filepath = full_path
        logging.info(f"Rendering image to: {full_path}...")
        bpy.ops.render.render(write_still=True)
        logging.info("Render complete.")
    except Exception as e:
        logging.error(f"Failed to render image {filepath_no_ext}: {e}\n{traceback.format_exc()}")


def assign_materials_and_names(parts_list):
    """Assigns materials based on heuristics and generates metadata."""
    metadata = {
        'model_id': MODEL_NAME, # Initial ID, might be updated by build_pdf
        'title': ' '.join(MODEL_NAME.split('_')).title(),
        'parts': [],
        'steps': []
    }
    if not INSIDE_BLENDER: return metadata # Return empty metadata if not in Blender

    part_materials = {} # Cache created materials
    part_counts = {}
    processed_parts_info = []

    logging.info(f"Assigning materials and names to {len(parts_list)} parts...")

    for i, part in enumerate(parts_list):
        # Basic check for valid part object
        if not part or not hasattr(part, 'dimensions') or not hasattr(part, 'name') or not hasattr(part, 'data'):
             logging.warning(f"Skipping invalid object at index {i}")
             continue
        if part.type != 'MESH':
             logging.warning(f"Skipping non-mesh object: {part.name} at index {i}")
             continue


        dims = part.dimensions
        # Handle potential zero dimensions safely
        height = dims.z if dims.z > 1e-6 else 1e-6
        width = dims.x if dims.x > 1e-6 else 1e-6
        depth = dims.y if dims.y > 1e-6 else 1e-6
        volume = height * width * depth
        max_dim = max(height, width, depth)
        min_dim = min(height, width, depth)

        # Heuristic for part type detection (can be refined)
        part_type = "part" # Default
        # Check volume first for very small parts
        if volume < 0.005 and max_dim < 0.15: # Slightly increased threshold for screws
            part_type = "screw"
        # Check aspect ratios only if not a screw
        elif height / max(width, depth, 1e-6) > 2.5: # Tall and thin parts are legs/supports (avoid division by zero)
            part_type = "leg"
        elif (width / max(height, depth, 1e-6) > 2.5) or (depth / max(height, width, 1e-6) > 2.5): # Long in X or Y
             # Check if relatively flat
             if min_dim / max_dim < 0.3:
                 part_type = "beam" # Long and relatively flat = beam
             else:
                 part_type = "leg" # Long but thicker = maybe a horizontal leg/support
        # Flat heuristic needs careful check for max_dim being non-zero
        elif max_dim > 1e-6 and abs(width - depth) < 0.15 * max(width, depth) and height / max_dim < 0.4: # Roughly square/round and flat (relaxed thresholds)
            part_type = "seat" # Could also be a tabletop

        # Get or create material
        material_key = part_type
        if material_key not in part_materials:
             color = PART_COLORS.get(material_key, PART_COLORS["part"])
             mat = create_material(f"{material_key.capitalize()}Material", color)
             if mat:
                 part_materials[material_key] = mat
             else: # Fallback if material creation fails
                 material_key = "part" # Use default part material
                 if material_key not in part_materials:
                     color = PART_COLORS["part"]
                     mat = create_material("PartMaterial", color)
                     if mat: # Ensure fallback creation worked
                        part_materials[material_key] = mat

        # Assign material
        target_material = part_materials.get(material_key)
        if target_material and part.data: # Check if part.data exists
             # Check if object has material slots before clearing/appending
             if not part.material_slots:
                 # Add a slot if none exist
                 bpy.ops.object.material_slot_add({'object': part})

             # Clear existing materials and add the new one
             # Using direct assignment is often safer than clear()+append() if slots exist
             if part.material_slots:
                 part.material_slots[0].material = target_material
                 # Remove extra slots if any
                 while len(part.material_slots) > 1:
                     bpy.ops.object.material_slot_remove({'object': part})
             else: # Should not happen after adding slot, but as fallback:
                  logging.warning(f"Part '{part.name}' still has no material slots after attempting add.")

        elif not part.data:
             logging.warning(f"Part '{part.name}' has no data attribute to assign material.")
        else:
             logging.warning(f"Could not get or create material '{material_key}' for part {part.name}")


        # Generate Name and Number
        part_counts[part_type] = part_counts.get(part_type, 0) + 1
        part_number_in_type = part_counts[part_type]
        part_name = f"{part_type.capitalize()} {part_number_in_type}"
        part.name = part_name # Rename the Blender object
        part_id = f"P{i+1:03d}" # Unique ID based on initial order

        part_info = {
            'name': part_name,
            'blender_name': part.name, # Store the actual object name used
            'number': part_id,
            'type': part_type,
            'quantity': 1 # Default, can be updated later if duplicate parts are detected
        }
        processed_parts_info.append(part_info)
        logging.info(f"Processed Part {i+1}: ID={part_id}, Name='{part_name}', Type='{part_type}'")

    # TODO: Add logic here to detect duplicate parts (e.g., by geometry hash or dimensions)
    # and update quantities, consolidating the parts list in metadata.
    # For now, assumes all separated parts are unique.
    metadata['parts'] = processed_parts_info

    return metadata


# --- Main Execution ---

def main():
    """Main logic for the script"""
    if not INSIDE_BLENDER:
         logging.error("This script must be run from within Blender.")
         print("To run: blender --background --python /path/to/blender_explode.py -- /path/to/model.fbx")
         return # Exit if not inside Blender
    if not model_path:
        logging.error("No valid model path provided to the script. Exiting.")
        return # Exit if no model path was determined

    logging.info(f"--- Starting Blender Explode Process for {MODEL_NAME} ---")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    clear_scene()

    if not import_model(model_path):
        sys.exit(1)

    parts = separate_and_get_parts()
    if not parts:
        logging.error("No parts to process. Exiting.")
        sys.exit(1)

    # Store original positions and hide all parts initially
    base_positions = {p.name: p.location.copy() for p in parts if p} # Store based on final name
    for part in parts:
        if part: # Check if part is valid
             # base_positions[part.name] = part.location.copy() # Already done above
             part.hide_render = True # Start with all hidden for steps
             part.hide_viewport = True # Hide in viewport too for clarity if running with UI

    # Assign materials, names, and create initial metadata
    metadata = assign_materials_and_names(parts) # This renames parts! Need to update base_positions keys if needed? No, key is name.

    # Ensure base_positions reflects the final names assigned by assign_materials_and_names
    # This might be redundant if assign_materials_and_names doesn't change names already in base_positions
    # but safer to rebuild or update if names change significantly.
    # For simplicity, assume names assigned are stable enough for now. Check logs if issues arise.


    # Setup scene elements (lights, camera, render settings)
    setup_scene()

    # --- Render Overview Image ---
    logging.info("Rendering Overview Image...")
    for part in parts: # Make all parts visible
        if part:
             part.hide_render = False
             part.hide_viewport = False
             if part.name in base_positions: # Reset position just in case
                 part.location = base_positions[part.name].copy()
             else:
                 logging.warning(f"Part '{part.name}' not found in base_positions for overview render.")

    # Deselect all before framing
    if bpy.ops.object.select_all.poll(): bpy.ops.object.select_all(action='DESELECT')
    frame_objects(parts) # Frame all parts in their assembled state
    render_image(os.path.join(OUTPUT_DIR, "overview"))

    # --- Render Parts Diagram ---
    logging.info("Rendering Parts Diagram...")
    # Arrange parts in a grid for the diagram
    total_parts = len(parts)
    if total_parts == 0:
         logging.warning("No parts to arrange for diagram.")
         has_parts_diagram = False
    else:
        has_parts_diagram = True
        grid_size = math.ceil(math.sqrt(total_parts))
        # Calculate spacing based on average size, ensure minimum
        avg_part_size = sum(get_object_size(p) for p in parts if p) / total_parts if total_parts > 0 else 1.0
        spacing = max(avg_part_size * 2.5, 1.5) # Increase spacing

        arranged_parts = []
        for i, part in enumerate(parts):
            if not part: continue
            row = i // grid_size
            col = i % grid_size
            part.location.x = col * spacing
            part.location.y = -row * spacing # Arrange top-to-bottom, left-to-right
            part.location.z = 0
            part.rotation_euler = (0, 0, 0) # Reset rotation for diagram view
            part.hide_render = False
            part.hide_viewport = False
            arranged_parts.append(part)

        # Frame the grid
        if bpy.ops.object.select_all.poll(): bpy.ops.object.select_all(action='DESELECT')
        frame_objects(arranged_parts)
        render_image(os.path.join(OUTPUT_DIR, "parts_diagram"))
        logging.info("Parts Diagram render complete.")
        # NOTE: Consider adding part locations to metadata here for post-processing labels

    metadata['has_parts_diagram'] = has_parts_diagram # Store whether diagram was generated

    # --- Render Assembly Steps ---
    logging.info("Rendering Assembly Steps...")
    # Reset part positions and visibility for steps
    active_parts_in_scene = [] # Track parts added in previous steps
    all_step_arrows = [] # Track all arrows created across steps
    step_data = []
    num_total_parts = len(parts)
    # Adjust step size dynamically based on target steps
    step_size = max(1, math.ceil(num_total_parts / TARGET_STEPS)) if TARGET_STEPS > 0 and num_total_parts > 0 else max(1, math.ceil(num_total_parts / 5))

    for i in range(0, num_total_parts, step_size):
        step_num = i // step_size
        logging.info(f"--- Processing Step {step_num+1} ---")

        # Define parts for this step and parts already assembled
        parts_in_this_step_indices = range(i, min(i + step_size, num_total_parts))
        # Ensure parts list is accessed correctly
        parts_in_this_step = [parts[j] for j in parts_in_this_step_indices if j < len(parts) and parts[j]]
        parts_already_assembled = active_parts_in_scene # From previous steps

        # Reset ALL parts to base positions before calculating explosion for *this* step
        for part in parts:
             if part and part.name in base_positions:
                 part.location = base_positions[part.name].copy()
             elif part: # Part might exist but wasn't in base_positions (e.g. added dynamically?)
                 logging.warning(f"Part '{part.name}' found but not in base_positions dict during step reset.")


        # Calculate center of already assembled parts (or origin if none)
        assembled_center = mathutils.Vector((0,0,0))
        if parts_already_assembled:
             valid_assembled = [p for p in parts_already_assembled if p and p.name in base_positions]
             if valid_assembled:
                # Use actual locations which should be base_positions
                assembled_center = sum((p.location for p in valid_assembled), mathutils.Vector()) / len(valid_assembled)


        # Explode parts *not yet assembled* for this step's view
        for j, part in enumerate(parts):
             if not part or j >= len(parts): continue # Check index bounds
             is_assembled = j < i
             if not is_assembled and part.name in base_positions:
                 # Calculate offset - Explode outwards from assembly center
                 explode_direction = (base_positions[part.name] - assembled_center)
                 if explode_direction.length < 0.1: # If part is near center, explode outwards/upwards
                      explode_direction = mathutils.Vector((math.cos(j*0.5)*0.5, math.sin(j*0.5)*0.5, 1.0))
                 # Ensure normalization is safe
                 if explode_direction.length > 1e-6:
                     explode_direction.normalize()
                 else: # Fallback direction
                     explode_direction = mathutils.Vector((0,0,1))


                 # Calculate distance based on how many parts are left, with capping
                 parts_remaining_factor = (num_total_parts - j) / num_total_parts if num_total_parts > 0 else 0 # Factor from 1 down to 0
                 distance = EXPLODE_FACTOR * (1 + parts_remaining_factor * 4) # Non-linear distance
                 distance = min(distance, MAX_EXPLODE_DISTANCE) # Cap the distance

                 offset = explode_direction * distance
                 part.location = base_positions[part.name] + offset # Move from base pos + offset
                 # Add slight vertical offset for clarity, relative to part size
                 part.location.z += EXPLODE_FACTOR * 0.8 * (1 + parts_remaining_factor) * get_object_size(part)


        # --- Arrow Creation & Destination Markers ---
        current_step_arrows = []
        parts_in_this_step_destinations = [] # Store destination marker objects
        for idx in parts_in_this_step_indices:
            if idx >= len(parts): continue
            part = parts[idx]
            if not part or part.name not in base_positions: continue

            destination = base_positions[part.name].copy()
            start_pos = part.location.copy() # Arrow starts from the *current* (exploded) position

            # Add a dummy object at the destination for framing purposes
            try:
                # Ensure not in edit mode
                if bpy.context.object and bpy.context.object.mode != 'OBJECT':
                     bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.empty_add(type='PLAIN_AXES', location=destination)
                dest_marker = bpy.context.active_object
                # Scale marker based on part size for better visibility during framing calc
                dest_marker.empty_display_size = max(0.1, get_object_size(part) * 0.3)
                dest_marker.name = f"DestMarker_Step{step_num+1}_{part.name}"
                parts_in_this_step_destinations.append(dest_marker)
            except Exception as marker_e:
                 logging.error(f"Could not create destination marker for {part.name}: {marker_e}")
                 continue # Skip arrow if marker fails


            # Check distance for arrow creation *after* potentially adjusting start_pos/destination
            if (start_pos - destination).length < 0.01:
                 logging.warning(f"Skipping arrow for {part.name} - start/end calculation resulted in distance < 0.01.")
                 continue

            arrow = create_arrow(start_pos, destination, part, name=f"Arrow_Step{step_num+1}_{part.name}")
            if arrow:
                current_step_arrows.append(arrow)
                all_step_arrows.append(arrow) # Add to master list for final cleanup

        # --- Set Visibility for Rendering ---
        # Objects actually rendered: assembled parts + exploded new parts + arrows for this step
        objects_to_render_this_step = []
        # Set assembled parts to final positions and make visible
        for part in parts_already_assembled:
             if part and part.name in base_positions:
                 part.location = base_positions[part.name].copy()
                 part.hide_render = False
                 part.hide_viewport = False
                 objects_to_render_this_step.append(part)
        # Keep new parts at exploded location and make visible
        for part in parts_in_this_step:
             if part:
                 part.hide_render = False
                 part.hide_viewport = False
                 objects_to_render_this_step.append(part)
        # Make current arrows visible
        for arrow in current_step_arrows:
             if arrow:
                 arrow.hide_render = False
                 arrow.hide_viewport = False
                 objects_to_render_this_step.append(arrow)

        # --- Frame the View (Using Destinations) ---
        # Objects used FOR FRAMING: assembled parts + destination markers of new parts
        objects_for_framing = []
        objects_for_framing.extend(p for p in parts_already_assembled if p) # Add valid assembled parts
        objects_for_framing.extend(p for p in parts_in_this_step_destinations if p) # Add destination markers

        # Ensure we have something to frame
        if not objects_for_framing: # If first step or only markers failed
             objects_for_framing.extend(p for p in parts_in_this_step if p) # Fallback: frame exploded parts

        logging.info(f"Framing based on {len(objects_for_framing)} objects (assembled + destinations).")
        if bpy.ops.object.select_all.poll(): bpy.ops.object.select_all(action='DESELECT')
        frame_objects(objects_for_framing) # Frame based on assembly + destinations

        # --- Hide Objects Not Being Rendered & Render ---
        # Determine names of objects that SHOULD be visible in the render
        render_obj_names = {obj.name for obj in objects_to_render_this_step if obj}

        # Iterate through ALL objects in the scene data
        for obj in bpy.data.objects:
            if obj.name in render_obj_names:
                 obj.hide_render = False # Ensure visible
                 obj.hide_viewport = False
            else:
                 # Hide everything else (including destination markers, other parts, other arrows)
                 obj.hide_render = True
                 obj.hide_viewport = True

        # *** ADDED logging for arrow visibility check ***
        for arrow in current_step_arrows:
            if arrow and arrow.name in bpy.data.objects:
                 logging.info(f"Arrow Check Before Render: {arrow.name} hide_render={bpy.data.objects[arrow.name].hide_render}")

        # Render the step image
        step_image_filename = f"step{(step_num):02d}"
        render_image(os.path.join(OUTPUT_DIR, step_image_filename))

        # --- Cleanup Destination Markers for this step ---
        for marker in parts_in_this_step_destinations:
            if marker and marker.name in bpy.data.objects:
                bpy.data.objects.remove(marker, do_unlink=True)
        parts_in_this_step_destinations.clear()

        # --- Update state for next loop ---
        # Add parts from this step to the list of assembled parts
        active_parts_in_scene.extend(p for p in parts_in_this_step if p)

        # Store step metadata
        step_parts_info = [p_info for p_info in metadata['parts'] if p_info['blender_name'] in [part.name for part in parts_in_this_step if part]]
        caption_parts = [f"{p['name']} ({p['number']})" for p in step_parts_info] # e.g., "Leg 1 (P001)"

        if i == 0:
            caption = f"Start assembly with: {', '.join(caption_parts)}."
        else:
            caption = f"Attach {', '.join(caption_parts)} as shown."

        step_data.append({
            'image': f"{step_image_filename}.png",
            'caption': caption,
            'parts_added_ids': [p['number'] for p in step_parts_info]
        })
        # --- End of Step Loop ---

    # --- Final Assembly Image ---
    logging.info("Rendering Final Assembly Image...")
    # Make all parts visible in their final positions
    for part in parts:
        if part and part.name in base_positions:
            part.location = base_positions[part.name].copy()
            part.hide_render = False
            part.hide_viewport = False

    # Hide/Remove all arrows created during steps
    logging.info(f"Cleaning up {len(all_step_arrows)} step arrows...")
    for arrow in list(all_step_arrows): # Use list copy
        if arrow and arrow.name in bpy.data.objects:
             try:
                bpy.data.objects.remove(bpy.data.objects[arrow.name], do_unlink=True)
             except Exception as rem_e:
                  logging.warning(f"Could not remove final arrow {arrow.name}: {rem_e}")
        if arrow in all_step_arrows: all_step_arrows.remove(arrow) # Remove from tracking list regardless


    # Hide any other remaining objects that aren't part of the main assembly
    base_part_names = {p.name for p in parts if p}
    for obj in bpy.data.objects:
         if obj.name not in base_part_names:
             # Keep lights and camera, hide everything else
             if obj.type not in {'LIGHT', 'CAMERA'}:
                 obj.hide_render = True
                 obj.hide_viewport = True

    if bpy.ops.object.select_all.poll(): bpy.ops.object.select_all(action='DESELECT')
    frame_objects(parts) # Frame final assembly
    render_image(os.path.join(OUTPUT_DIR, "final_assembly"))

    # Add final step metadata
    step_data.append({
        'image': "final_assembly.png",
        'caption': "Assembly complete.",
        'parts_added_ids': []
    })

    metadata['steps'] = step_data

    # --- Calculate Estimated Time ---
    num_parts = len(metadata['parts'])
    num_steps = len(metadata['steps']) -1 # Exclude final image
    time_estimate_minutes = max(5, num_parts * 1 + num_steps * 2) # Adjusted heuristic
    metadata['time_estimate'] = f"{time_estimate_minutes} minutes"

    # --- Save Metadata ---
    try:
        # Ensure output directory exists one last time
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(METADATA_FILE, 'w') as f:
            json.dump(metadata, f, indent=2)
        logging.info(f"Metadata saved to {METADATA_FILE}")
    except Exception as e:
        logging.error(f"Failed to save metadata: {e}")

    logging.info(f"--- Blender Explode Process Finished for {MODEL_NAME} ---")


# Standard Python entry point check
if __name__ == "__main__":
    # Only run the main logic if inside Blender, otherwise this file is just for import/linting
    if INSIDE_BLENDER:
        main()
    else:
        print("Script loaded outside Blender (e.g., for linting). Main execution skipped.")