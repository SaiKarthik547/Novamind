extends Node

var hub: CommandHub
var player: Player
var visualizer: AgentVisualizer
var diagnostics: DiagnosticsOverlay
var terminal: Control

func _ready():
	print("Main: Booting Spatial Shell...")
	
	# Instantiate Hub
	hub = CommandHub.new()
	add_child(hub)
	
	# Instantiate Player
	player = Player.new()
	player.position = Vector3(0, 20, 0) # Drop from sky onto voxel floor
	add_child(player)
	
	# Instantiate Visualizer
	visualizer = AgentVisualizer.new()
	add_child(visualizer)
	
	# Instantiate Diagnostics
	var diag_script = load("res://DiagnosticsOverlay.gd")
	diagnostics = diag_script.new()
	add_child(diagnostics)
	
	# Keep the old Terminal as an overlay UI
	# We load the script directly and attach to a new Control node
	var term_script = load("res://Terminal.gd")
	if term_script:
		terminal = Control.new()
		terminal.set_script(term_script)
		terminal.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		
		var canvas = CanvasLayer.new()
		canvas.add_child(terminal)
		add_child(canvas)
		
		# Hook up the input manager state machine logic
		# Terminal toggles mouse mode
		terminal.gui_input.connect(_on_terminal_input)

func _process(delta):
	# If terminal is active, unlock mouse, else lock mouse
	if Input.is_action_just_pressed("toggle_terminal"):
		if terminal.visible:
			terminal.hide()
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		else:
			terminal.show()
			Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

func _on_terminal_input(event):
	pass # Handle Terminal specific input if needed
