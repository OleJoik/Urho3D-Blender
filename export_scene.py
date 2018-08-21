
#
# This script is licensed as public domain.
#

from .utils import PathType, GetFilepath, CheckFilepath, \
                   FloatToString, Vector3ToString, Vector4ToString, \
                   WriteXmlFile

from xml.etree import ElementTree
from mathutils import Vector, Quaternion, Matrix
import bpy
import os
import logging
import math

log = logging.getLogger("ExportLogger")


#-------
# Utils
#-------

# Get the object quaternion rotation, convert if it uses other rotation modes
def GetQuatenion(obj):
    # Quaternion mode
    if obj.rotation_mode == 'QUATERNION':
        return obj.rotation_quaternion
    # Axis Angle mode
    if obj.rotation_mode == 'AXIS_ANGLE':
        rot = obj.rotation_axis_angle
        return Quaternion(Vector((rot[1], rot[2], rot[3])), rot[0])
    # Euler mode
    return obj.rotation_euler.to_quaternion()


#-------------------------
# Scene and nodes classes
#-------------------------

# Options for scene and nodes export
class SOptions:
    def __init__(self):
        self.doSelectedPrefab = False
        self.doIndividualPrefab = False
        self.doCollectivePrefab = False
        self.doScenePrefab = False
        self.physics = False
        self.mergeObjects = False
        self.shape = None
        self.shapeItems = None
        self.trasfObjects = False
        self.globalOrigin = False
        self.orientation = Quaternion((1.0, 0.0, 0.0, 0.0))

class UrhoSceneMaterial:
    def __init__(self):
        # Material name
        self.name = None
        # List\Tuple of textures
        self.texturesList = None

    def LoadMaterial(self, uExportData, uGeometry):
        self.name = uGeometry.uMaterialName
        for uMaterial in uExportData.materials:
            if uMaterial.name == self.name:
                self.texturesList = uMaterial.getTextures()
                break

class UrhoSceneModel:
    def __init__(self):
        # Model name
        self.name = None
        # Blender object name
        self.blenderName = None
        # Parent Blender object name
        self.parentBlenderName = None
        # Model type
        self.type = None
        # List of UrhoSceneMaterial
        self.materialsList = []
        # Model bounding box
        self.boundingBox = None
        # Model position
        self.position = Vector()
        # Model rotation
        self.rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
        # Model scale
        self.scale = Vector((1.0, 1.0, 1.0))

    def LoadModel(self, uExportData, uModel, blenderObjectName, sOptions):
        self.name = uModel.name

        self.blenderName = blenderObjectName
        if self.blenderName:
            object = bpy.data.objects[self.blenderName]

            # Get the local matrix (relative to parent)
            objMatrix = object.matrix_local
            # Reorient (normally only root objects need to be re-oriented but 
            # here we need to undo the previous rotation done by DecomposeMesh)
            if sOptions.orientation:
                om = sOptions.orientation.to_matrix().to_4x4()
                objMatrix = om * objMatrix * om.inverted()

            # Get pos/rot/scale
            pos = objMatrix.to_translation()
            rot = objMatrix.to_quaternion()
            scale = objMatrix.to_scale()

            # Convert pos/rot/scale
            self.position = Vector((pos.x, pos.z, pos.y))
            self.rotation = Quaternion((rot.w, -rot.x, -rot.z, -rot.y))
            self.scale = Vector((scale.x, scale.z, scale.y))

            # Get parent object
            parentObject = object.parent
            if parentObject and parentObject.type == 'MESH':
                self.parentBlenderName = parentObject.name

        if len(uModel.bones) > 0 or len(uModel.morphs) > 0:
            self.type = "AnimatedModel"
        else:
            self.type = "StaticModel"

        for uGeometry in uModel.geometries:
            uSceneMaterial = UrhoSceneMaterial()
            uSceneMaterial.LoadMaterial(uExportData, uGeometry)
            self.materialsList.append(uSceneMaterial)

        self.boundingBox = uModel.boundingBox

class UrhoScene:
    def __init__(self, blenderScene):
        # Blender scene name
        self.blenderSceneName = blenderScene.name
        # List of UrhoSceneModel
        self.modelsList = []
        # List of all files
        self.files = {}

    def LoadScene(self, uExportData, blenderObjectName, sOptions):
        for uModel in uExportData.models:
            uSceneModel = UrhoSceneModel()
            uSceneModel.LoadModel(uExportData, uModel, blenderObjectName, sOptions)
            self.modelsList.append(uSceneModel)

    def AddFile(self, pathType, name, fileUrhoPath):
        # Note: name must be unique in its type
        if not name:
            log.critical("Name null type:{:s} path:{:s}".format(pathType, fileUrhoPath) )
            return False
        if name in self.files:
            log.critical("Already added type:{:s} name:{:s}".format(pathType, name) )
            return False
        self.files[pathType+name] = fileUrhoPath
        return True

    def FindFile(self, pathType, name):
        if name is None:
            return ""
        try:
            return self.files[pathType+name]
        except KeyError:
            return ""


#------------
# Scene sort
#------------

# Hierarchical sorting (based on a post by Hyperboreus at SO)
class Node:
    def __init__(self, name):
        self.name = name
        self.children = []
        self.parent = None

    def to_list(self):
        names = [self.name]
        for child in self.children:
            names.extend(child.to_list())
        return names
            
class Tree:
    def __init__(self):
    	self.nodes = {}

    def push(self, item):
        name, parent = item
        if name not in self.nodes:
        	self.nodes[name] = Node(name)
        if parent:
            if parent not in self.nodes:
                self.nodes[parent] = Node(parent)
            if parent != name:
                self.nodes[name].parent = self.nodes[parent]
                self.nodes[parent].children.append(self.nodes[name])

    def to_list(self):
        names = []
        for node in self.nodes.values():
            if not node.parent:
                names.extend(node.to_list())
        return names

# Sort scene models by parent-child relation
def SceneModelsSort(scene):
    names_tree = Tree()
    for model in scene.modelsList:
        ##names_tree.push((model.objectName, model.parentBlenderName))
        names_tree.push((model.name, model.parentBlenderName))
    # Rearrange the model list in the new order
    orderedModelsList = []
    for name in names_tree.to_list():
        for model in scene.modelsList:
            ##if model.objectName == name:
            if model.name == name:
                orderedModelsList.append(model)
                # No need to reverse the list, we break straightway
                scene.modelsList.remove(model)
                break
    scene.modelsList = orderedModelsList


#--------------
# XML elements
#--------------

def XmlAddElement(parent, name, ids=None, values=None):
    if parent is not None:
        element = ElementTree.SubElement(parent, name)
    else:
        element = ElementTree.Element(name)
    if ids is not None:
        element.set("id", str(ids[name]))
        ids[name] += 1
    if values is not None:
        for name, value in values.items():
            element.set(name, str(value))
    return element

def XmlAddComponent(parent=None, type=None, ids=None):
    if parent is not None:
        element = ElementTree.SubElement(parent, "component")
    else:
        element = ElementTree.Element("component")
    if type is not None:
        element.set("type", str(type))
    if ids is not None:
        element.set("id", str(ids["component"]))
        ids["component"] += 1
    return element

def XmlAddAttribute(parent=None, name=None, value=None):
    if parent is not None:
        element = ElementTree.SubElement(parent, "attribute")
    else:
        element = ElementTree.Element("attribute")
    if name is not None:
        element.set("name", str(name))
    if value is not None:
        element.set("value", str(value))
    return element


#------------------------
# Export materials
#------------------------

def UrhoWriteMaterial(uScene, uMaterial, filepath, fOptions):

    material = XmlAddElement(None, "material")

    # Technique
    techniquFile = GetFilepath(PathType.TECHNIQUES, uMaterial.techniqueName, fOptions)
    XmlAddElement(material, "technique",
        values={"name": techniquFile[1]} )

    # Textures
    if uMaterial.diffuseTexName:
        XmlAddElement(material, "texture",
            values={"unit": "diffuse", "name": uScene.FindFile(PathType.TEXTURES, uMaterial.diffuseTexName)} )

    if uMaterial.normalTexName:
        XmlAddElement(material, "texture",
            values={"unit": "normal", "name": uScene.FindFile(PathType.TEXTURES, uMaterial.normalTexName)} )

    if uMaterial.specularTexName:
        XmlAddElement(material, "texture",
            values={"unit": "specular", "name": uScene.FindFile(PathType.TEXTURES, uMaterial.specularTexName)} )

    if uMaterial.emissiveTexName:
        XmlAddElement(material, "texture",
            values={"unit": "emissive", "name": uScene.FindFile(PathType.TEXTURES, uMaterial.emissiveTexName)} )

    # PS defines
    if uMaterial.psdefines != "":
        XmlAddElement(material, "shader",
            values={"psdefines": uMaterial.psdefines.lstrip()} )

    # VS defines
    if uMaterial.vsdefines != "":
        XmlAddElement(material, "shader",
            values={"vsdefines": uMaterial.vsdefines.lstrip()} )

    # Parameters
    if uMaterial.diffuseColor:
        XmlAddElement(material, "parameter",
            values={"name": "MatDiffColor", "value": Vector4ToString(uMaterial.diffuseColor)} )

    if uMaterial.specularColor:
        XmlAddElement(material, "parameter",
            values={"name": "MatSpecColor", "value": Vector4ToString(uMaterial.specularColor)} )

    if uMaterial.emissiveColor:
        XmlAddElement(material, "parameter",
            values={"name": "MatEmissiveColor", "value": Vector3ToString(uMaterial.emissiveColor)} )

    if uMaterial.twoSided:
        XmlAddElement(material, "cull",
            values={"value": "none"} )
        XmlAddElement(material, "shadowcull",
            values={"value": "none"} )

    WriteXmlFile(material, filepath, fOptions)

def UrhoWriteMaterialsList(uScene, uModel, filepath):

    # Search for the model in the UrhoScene
    for uSceneModel in uScene.modelsList:
        if uSceneModel.name == uModel.name:
            break
    else:
        return

    # Get the model materials and their corresponding file paths
    content = ""
    for uSceneMaterial in uSceneModel.materialsList:
        file = uScene.FindFile(PathType.MATERIALS, uSceneMaterial.name)
        # If the file is missing add a placeholder to preserve the order
        if not file:
            file = "null"
        content += file + "\n"

    try:
        file = open(filepath, "w")
    except Exception as e:
        log.error("Cannot open file {:s} {:s}".format(filepath, e))
        return
    file.write(content)
    file.close()


#------------------------
# Export scene and nodes
#------------------------

def UrhoExportScene(context, uScene, sOptions, fOptions):

    ids = {}
    ids["scene"] = 1
    ids["node"] = 0x1000000
    ids["component"] = 1

    # Root XML element
    root = XmlAddElement(None, "scene", ids=ids)
    XmlAddComponent(root, type="Octree", ids=ids)
    XmlAddComponent(root, type="DebugRenderer", ids=ids)
    comp = XmlAddComponent(root, type="Light", ids=ids)
    XmlAddAttribute(comp, name="Light Type", value="Directional")
    if sOptions.physics:
        XmlAddComponent(root, type="PhysicsWorld", ids=ids)

    # Root node
    ids["component"] = 0x1000000
    rootNode = XmlAddElement(root, "node", ids=ids)
    XmlAddAttribute(rootNode, name="Name", value=uScene.blenderSceneName)

    # Create physics stuff for the root node
    if sOptions.physics:
        comp = XmlAddComponent(rootNode, type="RigidBody", ids=ids)
        XmlAddAttribute(comp, name="Collision Layer", value="2")
        XmlAddAttribute(comp, name="Use Gravity", value="false")

        physicsModelFile = GetFilepath(PathType.MODELS, "Physics", fOptions)[1]
        comp = XmlAddComponent(rootNode, type="CollisionShape", ids=ids)
        XmlAddAttribute(comp, name="Shape Type", value="TriangleMesh")
        XmlAddAttribute(comp, name="Model", value="Model;" + physicsModelFile)

    if sOptions.trasfObjects and sOptions.globalOrigin:
        log.warning("To export objects transformations you should use Origin = Local")

    # Sort the models by parent-child relationship
    SceneModelsSort(uScene)

    # Model nodes collection
    nodes = {}

    # Export each model object as a node
    for uSceneModel in uScene.modelsList:

        # Blender name is surely unique
        blenderName = uSceneModel.blenderName

        # Find the XML element of the model parent if it exists
        parent = rootNode
        if uSceneModel.type == "StaticModel":
            parentName = uSceneModel.parentBlenderName
            if parentName in nodes:
                parent = nodes[parentName]

        # Get model file relative path
        modelFile = uScene.FindFile(PathType.MODELS, uSceneModel.name)

        # Gather materials
        materials = ""
        for uSceneMaterial in uSceneModel.materialsList:
            file = uScene.FindFile(PathType.MATERIALS, uSceneMaterial.name)
            materials += ";" + file

        # Generate the node XML content
        node = XmlAddElement(parent, "node", ids=ids)
        nodes[blenderName] = node
        XmlAddAttribute(node, name="Name", value=uSceneModel.name)
        if sOptions.trasfObjects:
            XmlAddAttribute(node, name="Position", value=Vector3ToString(uSceneModel.position))
            XmlAddAttribute(node, name="Rotation", value=Vector4ToString(uSceneModel.rotation))
            XmlAddAttribute(node, name="Scale", value=Vector3ToString(uSceneModel.scale))

        comp = XmlAddComponent(node, type=uSceneModel.type, ids=ids)
        XmlAddAttribute(comp, name="Model", value="Model;" + modelFile)
        XmlAddAttribute(comp, name="Material", value="Material" + materials)

        if sOptions.physics:
            shapeType = sOptions.shape
            obj = bpy.data.objects[blenderName]
            if not sOptions.mergeObjects and obj.game.use_collision_bounds: ## Blender game engine?
                for shapeItems in sOptions.shapeItems:
                    if shapeItems[0] == obj.game.collision_bounds_type:
                        shapeType = shapeItems[1]
                        break

            # Use model's bounding box to compute CollisionShape's size and offset
            bbox = uSceneModel.boundingBox
            # Size
            shapeSize = Vector()
            if bbox.min and bbox.max:
                shapeSize.x = bbox.max[0] - bbox.min[0]
                shapeSize.y = bbox.max[1] - bbox.min[1]
                shapeSize.z = bbox.max[2] - bbox.min[2]
            # Offset
            shapeOffset = Vector()
            if bbox.max:
                shapeOffset.x = bbox.max[0] - shapeSize.x / 2
                shapeOffset.y = bbox.max[1] - shapeSize.y / 2
                shapeOffset.z = bbox.max[2] - shapeSize.z / 2

            comp = XmlAddComponent(node, type="RigidBody", ids=ids)
            XmlAddAttribute(comp, name="Collision Layer", value="2")
            XmlAddAttribute(comp, name="Use Gravity", value="false")

            comp = XmlAddComponent(node, type="CollisionShape", ids=ids)
            XmlAddAttribute(comp, name="Shape Type", value=shapeType)
            if shapeType == "TriangleMesh":
                XmlAddAttribute(comp, name="Model", value="Model;" + modelFile)
            else:
                XmlAddAttribute(comp, name="Size", value=Vector3ToString(shapeSize))
                XmlAddAttribute(comp, name="Offset Position", value=Vector3ToString(shapeOffset))

    # Export full scene: scene elements + scene node
    if sOptions.doScenePrefab: 
        filepath = GetFilepath(PathType.SCENES, uScene.blenderSceneName, fOptions)
        if CheckFilepath(filepath[0], fOptions):
            log.info( "Creating scene {:s}".format(filepath[1]) )
            WriteXmlFile(root, filepath[0], fOptions)

    # Export scene node
    if sOptions.doCollectivePrefab: 
        filepath = GetFilepath(PathType.OBJECTS, uScene.blenderSceneName, fOptions)
        if CheckFilepath(filepath[0], fOptions):
            log.info( "Creating scene prefab {:s}".format(filepath[1]) )
            WriteXmlFile(rootNode, filepath[0], fOptions)

    # Export individual nodes including child nodes
    if sOptions.doIndividualPrefab or sOptions.doSelectedPrefab:
        usedNames = []
        selectedNames = []
        for obj in context.selected_objects:
            selectedNames.append(obj.name)

        for blenderName, xmlNode in nodes.items():
            if sOptions.doSelectedPrefab and not blenderName in selectedNames: 
                continue
            # From Blender name to plain name, this is useful for LODs but we can have 
            # duplicates, in that case fallback to the Blender name
            name = None
            for uSceneModel in uScene.modelsList:
                if uSceneModel.blenderName == blenderName:
                    name = uSceneModel.name
                    break
            if not name or name in usedNames:
                name = blenderName
            usedNames.append(name)

            filepath = GetFilepath(PathType.OBJECTS, name, fOptions)
            if CheckFilepath(filepath[0], fOptions):
                log.info( "Creating object prefab {:s}".format(filepath[1]) )
                WriteXmlFile(xmlNode, filepath[0], fOptions)

