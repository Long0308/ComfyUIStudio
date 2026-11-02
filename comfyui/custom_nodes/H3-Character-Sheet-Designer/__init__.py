"""Register all character-sheet nodes across versions for full backwards and flat-workflow compatibility."""
from .h3_character_sheet.node import H3CharacterSheetDesigner
from .h3_character_sheet.multi_reference_node import H3CharacterSheetDesignerMultiReference
from .h3_character_sheet.reference_v11_node import H3CharacterSheetDesignerReferenceV11
from .h3_character_sheet.reference13_node import H3CharacterSheetDesignerReference13
from .h3_character_sheet.reference13_preview import register_routes as register_reference13_routes
from .h3_character_sheet.reference_v13_node import H3CharacterSheetDesignerReferenceV13
from .h3_character_sheet.reference_v13_preview import register_routes as register_v13_routes
from .h3_character_sheet.preview import register_routes as register_preview_routes

NODE_CLASS_MAPPINGS = {
    "H3CharacterSheetDesigner": H3CharacterSheetDesigner,
    "H3CharacterSheetDesignerMultiReference": H3CharacterSheetDesignerMultiReference,
    "H3CharacterSheetDesignerReferenceV11": H3CharacterSheetDesignerReferenceV11,
    "H3CharacterSheetDesignerReference13": H3CharacterSheetDesignerReference13,
    "H3CharacterSheetDesignerReferenceV13": H3CharacterSheetDesignerReferenceV13,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "H3CharacterSheetDesigner": "H3 Character Sheet Designer",
    "H3CharacterSheetDesignerMultiReference": "H3 Character Sheet Designer MultiReference",
    "H3CharacterSheetDesignerReferenceV11": "H3 Character Sheet Designer v1.1",
    "H3CharacterSheetDesignerReference13": "H3 Character Sheet Designer v1.2.2",
    "H3CharacterSheetDesignerReferenceV13": "H3 Character Sheet Designer v1.3.0",
}
WEB_DIRECTORY = "./web"
register_preview_routes()
register_reference13_routes()
register_v13_routes()
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
