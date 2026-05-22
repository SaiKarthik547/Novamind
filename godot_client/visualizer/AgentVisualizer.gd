extends Node3D
class_name AgentVisualizer

var active_agents: Dictionary = {}

func _ready():
	print("AgentVisualizer: Initialized")
	var network = get_node_or_null("/root/NetworkManager")
	if network:
		network.state_updated.connect(_on_state_updated)

func _on_state_updated(data: Dictionary):
	var action = data.get("action", "")
	if action == "agent_event":
		var event = data.get("payload", {})
		var msg_type = event.get("type", "")
		var agent_id = event.get("data", {}).get("agent_id", "system")
		var task_name = event.get("data", {}).get("name", "Unknown Task")
		
		match msg_type:
			"task_started":
				_spawn_agent_hologram(agent_id, task_name)
			"task_completed":
				_despawn_agent_hologram(agent_id, true)
			"task_failed":
				_despawn_agent_hologram(agent_id, false)
			"tool_call_start":
				_update_agent_hologram(agent_id, "tool_active")
			"tool_call_end":
				_update_agent_hologram(agent_id, "tool_idle")

func _spawn_agent_hologram(agent_id: String, task_name: String):
	if active_agents.has(agent_id):
		return
		
	# Create a visual representation (e.g. a floating pillar or particle system)
	var agent_node = Node3D.new()
	var mesh_inst = MeshInstance3D.new()
	var mesh = CylinderMesh.new()
	mesh.height = 3.0
	mesh.top_radius = 0.5
	mesh.bottom_radius = 0.5
	
	var mat = StandardMaterial3D.new()
	mat.albedo_color = Color(0.2, 0.8, 1.0, 0.5)
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.emission_enabled = true
	mat.emission = Color(0.2, 0.8, 1.0)
	mat.emission_energy = 2.0
	mesh.material = mat
	
	mesh_inst.mesh = mesh
	mesh_inst.position = Vector3(randf_range(-5, 5), 1.5, randf_range(-5, 5))
	
	var label = Label3D.new()
	label.text = agent_id + "\n" + task_name
	label.position = Vector3(0, 2.0, 0)
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	
	agent_node.add_child(mesh_inst)
	agent_node.add_child(label)
	add_child(agent_node)
	
	active_agents[agent_id] = agent_node
	print("Spawned hologram for agent: ", agent_id)

func _despawn_agent_hologram(agent_id: String, success: bool):
	if active_agents.has(agent_id):
		var node = active_agents[agent_id]
		# In a real system, trigger a dissolve shader or particle burst here
		node.queue_free()
		active_agents.erase(agent_id)
		print("Despawned hologram for agent: ", agent_id, " (Success: ", success, ")")

func _update_agent_hologram(agent_id: String, state: String):
	if active_agents.has(agent_id):
		var node = active_agents[agent_id]
		var mesh_inst = node.get_child(0) as MeshInstance3D
		var mat = mesh_inst.mesh.material as StandardMaterial3D
		
		if state == "tool_active":
			mat.emission = Color(1.0, 0.8, 0.2) # Yellow
		elif state == "tool_idle":
			mat.emission = Color(0.2, 0.8, 1.0) # Blue
