extends CharacterBody3D
class_name Player

const SPEED = 5.0
const JUMP_VELOCITY = 4.5

var gravity = ProjectSettings.get_setting("physics/3d/default_gravity")
var is_first_person = false

var head: Node3D
var spring_arm: SpringArm3D
var camera: Camera3D

func _ready():
	# Create physical collision
	var collision = CollisionShape3D.new()
	var shape = CapsuleShape3D.new()
	collision.shape = shape
	collision.position = Vector3(0, 1, 0) # Center capsule
	add_child(collision)
	
	# Visual Placeholder
	var mesh_inst = MeshInstance3D.new()
	var mesh = CapsuleMesh.new()
	mesh_inst.mesh = mesh
	mesh_inst.position = Vector3(0, 1, 0)
	add_child(mesh_inst)

	# Camera setup
	head = Node3D.new()
	head.position = Vector3(0, 1.6, 0)
	add_child(head)
	
	spring_arm = SpringArm3D.new()
	spring_arm.spring_length = 3.0
	spring_arm.position = Vector3(0, 0, 0)
	head.add_child(spring_arm)
	
	camera = Camera3D.new()
	spring_arm.add_child(camera)
	
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _unhandled_input(event):
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		head.rotate_y(-event.relative.x * 0.005)
		spring_arm.rotate_x(-event.relative.y * 0.005)
		spring_arm.rotation.x = clamp(spring_arm.rotation.x, -PI/2.5, PI/2.5)

	if event.is_action_pressed("toggle_camera"):
		is_first_person = !is_first_person
		if is_first_person:
			spring_arm.spring_length = 0.0
		else:
			spring_arm.spring_length = 3.0

func _physics_process(delta):
	# Add the gravity.
	if not is_on_floor():
		velocity.y -= gravity * delta

	# Handle jump.
	if Input.is_action_just_pressed("jump") and is_on_floor():
		velocity.y = JUMP_VELOCITY

	# Get the input direction and handle the movement/deceleration.
	# As good practice, you should replace UI actions with custom gameplay actions.
	var input_dir = Input.get_vector("move_left", "move_right", "move_forward", "move_backward")
	var direction = (head.transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
	
	if direction:
		velocity.x = direction.x * SPEED
		velocity.z = direction.z * SPEED
	else:
		velocity.x = move_toward(velocity.x, 0, SPEED)
		velocity.z = move_toward(velocity.z, 0, SPEED)

	move_and_slide()
