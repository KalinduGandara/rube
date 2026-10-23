## System Architecture: Rube Goldberg AI-Blender Framework

This document outlines the technical blueprint required for an AI coding agent to implement the high-level Python framework inside Blender.

### 1. Architectural Layers

The framework must be strictly divided into three layers to insulate the generative AI from Blender's internal context and state changes.

* **Layer 1: The AI-Facing API (Declarative):** A pure Python interface with zero `bpy` dependencies exposed to the LLM generating the machines. It stores intent and parameters in memory.
* **Layer 2: The Translation Engine (Imperative):** Parses the objects created in Layer 1 and executes the corresponding `bpy.ops` and `bpy.data` commands to build the 3D meshes and assign physics.
* **Layer 3: The Director & Physics Manager:** Handles the global scene settings, rigid body world configuration, caching, camera animation, and rendering pipeline.

---

### 2. Class Blueprints & API Contract (Layer 1 & 2)

The AI agent implementing this must construct the following class hierarchy.

#### The `Machine` Class (Singleton Director)

Acts as the central registry and scene manager.

* **Methods to implement:**
* `__init__()`: Clears the default Blender scene (`bpy.ops.wm.read_factory_settings(use_empty=True)`).
* `add(entity)`: Registers a physical object.
* `build()`: Iterates through all registered entities and calls their internal `.spawn()` methods.
* `bake_physics()`: Triggers the Rigid Body World cache bake.
* `preview_render(filepath)`: Triggers an OpenGL viewport render (`bpy.ops.render.opengl()`) for rapid AI validation.



#### The `Entity` Base Class

All physical objects inherit from this.

* **Properties:** `name`, `location` (x,y,z tuple), `rotation` (x,y,z tuple), `scale`.
* **Physics Properties:** `mass`, `friction`, `bounciness`, `is_dynamic` (True for falling objects, False for static ramps).
* **Internal Method:** `_apply_rigid_body()`: Standardized function that assigns `bpy.ops.rigidbody.object_add()` and maps the physics properties to `bpy.context.object.rigid_body`.

#### Specific Primitive Classes

* **`Ball(Entity)`**
* *Action:* Spawns a UV Sphere (`bpy.ops.mesh.primitive_uv_sphere_add`).
* *Physics:* Collision shape must be explicitly set to `'SPHERE'`.


* **`Domino(Entity)`**
* *Action:* Spawns a Cube (`primitive_cube_add`) scaled to domino proportions (e.g., 0.1, 0.4, 0.8).
* *Physics:* Collision shape set to `'BOX'`.


* **`Ramp(Entity)`**
* *Action:* Spawns a Cube, scaled wide and long, rotated to act as a slope.
* *Physics:* `is_dynamic=False` (Passive rigid body). Collision shape `'BOX'` or `'MESH'`.



#### Procedural Utility Functions (Crucial for AI)

AI models cannot calculate complex spatial arrays. The framework must provide mathematical generators.

* `create_domino_chain(start_pos, end_pos, count)`: Generates a Bezier curve between two points and spawns `Domino` instances at equal intervals along the tangent of the curve.
* `create_spiral_ramp(center_pos, radius, height, revolutions)`: Generates a coiled mesh acting as a marble run.

#### The `CameraOperator` Class

* **Methods to implement:**
* `set_static_view(location, look_at_target)`
* `follow(entity)`: Spawns a camera, adds a `TRACK_TO` constraint targeting the specific entity, and parents the camera to an offset location if tracking a moving ball.



---

### 3. Physics Stability & Determinism (Layer 3)

The most difficult part of the implementation is preventing the physics engine from glitching. The AI must enforce these specific Blender settings in the `Machine.build()` phase:

1. **Rigid Body World Steps:**
* `bpy.context.scene.rigidbody_world.steps_per_second = 240` (Default is 60. Rube Goldberg machines require high precision to prevent tunneling).
* `bpy.context.scene.rigidbody_world.solver_iterations = 20`


2. **Collision Margins:**
* Every entity's `_apply_rigid_body()` method must set `bpy.context.object.rigid_body.use_margin = True` and `margin = 0.001`.


3. **Origin Points:**
* The framework must automatically apply scale and reset geometry origins to the center of mass (`bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_MASS')`) after spawning, otherwise physics calculations will rotate objects around incorrect pivots.



---

### 4. Implementation Constraints for the Coding Agent

Provide these exact constraints to the AI generating the Python framework:

* **Context Safety:** Never rely on `bpy.context.active_object` spanning across multiple function calls. Always store object references in variables immediately upon creation:
```python
bpy.ops.mesh.primitive_cube_add(...)
my_cube = bpy.context.active_object

```


* **Dependency Management:** Ensure the script runs entirely within Blender's bundled Python environment. Do not use `pip install` for external geometry libraries; use built-in `math` and `mathutils`.
* **Error Handling:** Implement try/except blocks around the physics baking process, as overlapping geometry at frame 1 will cause Bullet physics to throw exceptions or freeze.