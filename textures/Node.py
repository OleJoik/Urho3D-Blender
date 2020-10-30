import bpy
import os

ACCEPTED_FORMATS = [
    "BMP",
    "PNG",
    "TGA",
    "JPG",
]
def RepresentsInt(s):
    try:
        print("try: ",s)
        int(s)
        return True
    except ValueError:
        return False

class TextureNode():
    def __init__(self,node,cache):
        self.node = node #ShaderNodeTexImage
        self.cache = cache

        image = self.node.image
        if image: #save the image
            dir = self.cache.absolute_paths["textures"]
            if image in self.cache.textures:
                pass
            else:
                extensions = os.path.splitext(image.name)
                name = extensions[0]
                last = extensions[len(extensions)-1]

                if len(last) == 4 and RepresentsInt(last[1]) and RepresentsInt(last[2]) and RepresentsInt(last[3]):
                    extensions = os.path.splitext(name)
                    name = extensions[0]

                if not (image.file_format in ACCEPTED_FORMATS):
                    image.file_format = "PNG"

            #in the future sort this out by using cache unique name thing.
                name = name + "." + image.file_format.lower()
                self.name = name
                self.filepath = dir + "/" + name

    def getRelativePath(self):
        return self.cache.relative_paths["textures"] + "/" + self.name

    def getAbsolutePath(self):
        return self.filepath

    def save(self):
        image = self.node.image

        print("Saving image: ",self.name)
        old = image.colorspace_settings.name
        image.colorspace_settings.name = "Raw"
        image.save_render(self.filepath)
        image.colorspace_settings.name = old
