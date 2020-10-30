import bpy
import numbers
import os
from node.texture_node import TextureNode

MAT_TYPES = [
    "Principled BSDF",
    "Diffuse BSDF",
    "Mix Shader"
]
# int TU_DIFFUSE
# int TU_ALBEDOBUFFER
# int TU_NORMAL
# int TU_NORMALBUFFER
# int TU_SPECULAR
# int TU_EMISSIVE
# int TU_ENVIRONMENT
NAME_ORDER = [
    "Diffuse",
    "Specular",
    "Normal",
    "Emissive",
]
NAME_MAPPING = {
    "Base Color" : "Diffuse",
    "Emission" : "Emissive",
    "Normal" : "Normal",
    "Specular": "Specular"
}
NAME_MAPPING_SHORT = {
    "Diffuse" : "Diff",
    "Emissive" : "Emissive",
    "Specular" : "Spec"
}


# <material>
# 	 <technique name="Techniques/DiffUnlitAlphaGlow.xml" />
# 	 <parameter name="MatDiffColor" value="1 1 1 1"/>
#      <textures>
#          <TU_DIFFUSE>arcade.png</TU_DIFFUSE>
#      </textures>
# 	 <cull value="none" />
# </material>


class Material():
    def __init__(self, bpy_mat, cache):
        self.cache = cache
        self.mat = bpy_mat
        self.hasAlpha = False
        self.filename = None
        self.isSerialized = False

        self.surfaceName = None

    def getBlendMethod(self): #urho3d blend method
        blend_method = self.mat.blend_method
        if blend_method == "OPAQUE":
            return None
        elif blend_method == "CLIP":
            return "AlphaMask"
        else:
            return "Alpha"
            #trasparent


    def getNodeFromLink(self, dif, socket):
        try:
            #Get the link that input to 'dif' and 'socket'
            link = next( link for link in self.mat.node_tree.links if link.to_node == dif and link.to_socket == socket )
            return link.from_node

        except:
            return None

    def getName(self):
        return self.mat.name

    def parse(self):
        textures = {}
        colors = {}

        #print("--- nodes for " + self.mat.name + " ---")
        material_node = None
        for name,node in self.mat.node_tree.nodes.items():
            if name in MAT_TYPES:
                material_node = node
                self.surfaceName = name
        if material_node:
            inputs = material_node.inputs
            if self.surfaceName == "Mix Shader":
                fac = inputs["Fac"]
                link = fac.links[0]
                node = link.from_node #ShaderNodeTexImage
                textures["Diffuse"] = TextureNode(node, self.cache)
                self.hasAlpha = True
                self.isUnlit = True
            else:
                #print("- inputs -")
                #for name, model in inputs.items():
                #    print(name,model)
                #print("- -")
                for input_name,remaped_name in NAME_MAPPING.items():
                    target = inputs.get(input_name)
                    if target:
                        node = self.getNodeFromLink(material_node,target)
                        if isinstance(node, bpy.types.ShaderNodeTexImage):
                            textures[remaped_name] = TextureNode(node, self.cache)
                        else:
                            colors[remaped_name] = inputs[input_name].default_value

                node = self.getNodeFromLink(material_node,inputs["Alpha"])
                if isinstance(node, bpy.types.ShaderNodeTexImage):
                    self.hasAlpha = True
                self.isUnlit = self.mat.shadow_method == "NONE"


        self.textures = textures
        self.colors = colors

        self.surfaceName == "Mix Shader"
        self.ambientOcclusion = False

    def getTechniqueName(self):
        technique = ""

        if "Diffuse" in self.textures:
            technique = "Diff"
            if not self.isUnlit:
                if "Normal" in self.textures:
                    technique = technique + "Normal"
                    if "Specular" in self.textures:
                        technique = technique + "Spec"
                elif "Specular" in self.textures:
                    technique = technique + "Spec"
        else:
            technique = "NoTexture"

        if self.isUnlit:
            technique = technique + "Unlit"
        elif self.ambientOcclusion:
            technique = technique + "AO"


        if self.hasAlpha:
            technique = technique + self.getBlendMethod()


        return technique

    def convertColorToString(self, color):
        if isinstance(color, numbers.Number):
            color = [color,color,color,1]

        return " ".join(str(v) for v in color)

    def getRelativeFileName(self):
        dir = self.cache.relative_paths["materials"]
        return dir + "/" + self.filename

    def serialize(self):
        if self.isSerialized:
            return
        print("serializing material: ",self.getName())
        self.isSerialized = True
        self.parse()

        out = []
        out.append("<?xml version=\"1.0\"?>")
        out.append("<material>")
        out.append("	 <technique name=\"Techniques/"+self.getTechniqueName()+".xml\" />")

        if not ("Diffuse" in self.colors):
            out.append("	 <parameter name=\"MatDiffColor\" value=\"1 1 1 1\"/>")
        for full_name in NAME_ORDER:
            #print(full_name)
            #found in colors and in short name mapping, cuz if its not then dont bother.
            if full_name in self.colors and full_name in NAME_MAPPING_SHORT:
                #print(full_name)
                #for name,color in self.colors.items():
                #    print(name,color)
                color = self.colors[full_name]
                name = NAME_MAPPING_SHORT[full_name]
                color = self.convertColorToString(color)
                out.append("	 <parameter name=\"Mat"+name+"Color\" value=\""+color+"\"/>")



        if self.cache.exportSettings["Textures"]:
            out.append("     <textures>")

            for name in NAME_ORDER:
                if name in self.textures:
                    textureNode = self.textures[name]
                    unit = "TU_"+name.upper()
                    path = textureNode.getRelativePath()
                    out.append("        <" + unit + ">" + path + "</" + unit + ">")
                    textureNode.save()


            out.append("     </textures>")

        #out.append("	 <cull value=\"none\" />")
        out.append("</material>")

        dir = self.cache.absolute_paths["materials"]
        name = self.mat.name + ".xml"
        fname = dir +  "/" + name

        self.filename = name

        with open(fname, "w") as f:
            f.write("\n".join(out))

        return out
