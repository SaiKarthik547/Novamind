extends Control

var output_log: RichTextLabel
var input_field: LineEdit

func _ready():
	# Create UI programmatically to avoid brittle .tscn generation
	
	# Background
	var bg = ColorRect.new()
	bg.color = Color(0, 0, 0, 0.8)
	bg.set_anchors_preset(PRESET_FULL_RECT)
	add_child(bg)
	
	var vbox = VBoxContainer.new()
	vbox.set_anchors_preset(PRESET_FULL_RECT)
	vbox.add_theme_constant_override("margin_left", 20)
	vbox.add_theme_constant_override("margin_top", 20)
	vbox.add_theme_constant_override("margin_right", 20)
	vbox.add_theme_constant_override("margin_bottom", 20)
	add_child(vbox)
	
	var title = Label.new()
	title.text = "NovaMind Terminal | AI-Native Spatial Environment"
	title.add_theme_font_size_override("font_size", 24)
	vbox.add_child(title)
	
	output_log = RichTextLabel.new()
	output_log.bbcode_enabled = true
	output_log.text = "[color=green]Ready. Awaiting command...[/color]\n"
	output_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	vbox.add_child(output_log)
	
	input_field = LineEdit.new()
	input_field.placeholder_text = "> Type command here (e.g. 'Open my ML workspace')"
	input_field.text_submitted.connect(_on_text_submitted)
	vbox.add_child(input_field)
	
	# Focus input
	input_field.grab_focus()
	
	# Listen to NetworkManager
	NetworkManager.state_updated.connect(_on_state_updated)
	
	# Auto-trigger for vertical slice test
	var timer = Timer.new()
	timer.wait_time = 2.0
	timer.one_shot = true
	timer.timeout.connect(func(): _on_text_submitted("open my vscode workspace"))
	add_child(timer)
	timer.start()

func _on_text_submitted(text: String):
	if text.strip_edges() == "":
		return
		
	input_field.clear()
	output_log.text += "[color=white]> " + text + "[/color]\n"
	
	# Send to Python Core
	NetworkManager.send_message("EVENT", "user_command", {"text": text})

func _on_state_updated(data: Dictionary):
	var payload = data.get("payload", {})
	var msg = payload.get("message", "")
	var color = payload.get("color", "green")
	output_log.text += "[color=" + color + "]" + msg + "[/color]\n"
