extends Node3D
class_name CommandHub

var terrain: VoxelTerrain
var stream: VoxelStreamRegionFiles
var mesher: VoxelMesherBlocky

func _ready():
	print("CommandHub: Initializing Spatial Environment...")
	
	# Setup Lighting
	var light = DirectionalLight3D.new()
	light.shadow_enabled = true
	light.rotation_degrees = Vector3(-45, 45, 0)
	add_child(light)
	
	# Setup Environment (SSAO, Procedural Sky)
	var env = Environment.new()
	var sky = ProceduralSkyMaterial.new()
	env.background_mode = Environment.BG_SKY
	env.sky = Sky.new()
	env.sky.sky_material = sky
	env.ssao_enabled = true
	env.ssao_radius = 1.0
	env.ssao_intensity = 2.0
	env.sdfgi_enabled = false # Disabled for laptop performance
	
	var world_env = WorldEnvironment.new()
	world_env.environment = env
	add_child(world_env)
	
	# Setup Voxel Terrain
	terrain = VoxelTerrain.new()
	
	# We use a flat generator to create a baseline floor
	var generator = VoxelGeneratorFlat.new()
	generator.channel = VoxelBuffer.CHANNEL_TYPE
	
	# Blocky mesher for Minecraft/Roblox style
	mesher = VoxelMesherBlocky.new()
	
	terrain.generator = generator
	terrain.mesher = mesher
	
	add_child(terrain)
	print("CommandHub: Environment Initialized.")
