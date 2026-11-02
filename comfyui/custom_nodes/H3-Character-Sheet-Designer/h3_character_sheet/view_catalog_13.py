"""H3 view order and camera conventions; no image or model dependencies."""
from .compiler import BODY_IDS, PRESETS as LEGACY_PRESETS, VIEW_IDS as LEGACY_VIEW_IDS

PORTRAIT_IDS = ('face_front', 'face_left', 'face_right', 'face_3q_left', 'face_3q_right', 'face_back')
CLOTHING_IDS = ('clothing_front', 'clothing_back')
HELMET_IDS = ('helmet_front', 'helmet_3q_left', 'helmet_3q_right', 'helmet_side')
VEST_IDS = ('vest_front', 'vest_back', 'vest_3q')
PPE_IDS = (*HELMET_IDS, *VEST_IDS)
VIEW_IDS = (*PORTRAIT_IDS, *BODY_IDS, *CLOTHING_IDS, 'hands', 'feet', *PPE_IDS)
PRESETS = {**LEGACY_PRESETS, 'head': PORTRAIT_IDS, 'clothing': CLOTHING_IDS, 'ppe': PPE_IDS, 'newtecons_full': ('face_front', 'body_front', 'helmet_front', 'vest_front', 'vest_back'), 'detail': VIEW_IDS}
VIEW_DETAILS = {
    'face_front': ('front portrait', 'One front-facing bust, complete head and hair through the upper chest. Both eyes visible; no waist, legs or feet.'),
    'face_left': ('anatomical left-profile portrait', 'One strict anatomical left-profile bust, complete head and hair through the upper chest. The nose points to the RIGHT edge of the sheet, as in the H3 left-view convention. One visible eye; no front or three-quarter view.'),
    'face_right': ('anatomical right-profile portrait', 'One strict anatomical right-profile bust, complete head and hair through the upper chest. The nose points to the LEFT edge of the sheet. One visible eye; preserve asymmetric features rather than mirroring the person.'),
    'face_3q_left': ('anatomical left three-quarter portrait', 'One anatomical left three-quarter bust at 45 degrees, complete head and hair through the upper chest. The nose points toward the RIGHT edge. Both eyes visible with the farther eye foreshortened; not a front or strict profile view.'),
    'face_3q_right': ('anatomical right three-quarter portrait', 'One anatomical right three-quarter bust at 45 degrees, complete head and hair through the upper chest. The nose points toward the LEFT edge. Both eyes visible with the farther eye foreshortened; not a front or strict profile view.'),
    'face_back': ('rear portrait', 'One direct rear bust, complete back of head and hair through the upper chest. No face or eyes visible; do not turn the head.'),
    'body_front': ('full-body front', 'One full-body front view in a neutral standing pose. Include the complete head through both feet or footwear, with empty space above the head and beneath the soles.'),
    'body_left': ('full-body anatomical left profile', 'One strict anatomical left-profile full-body neutral standing view. Nose, chest and toes point to the RIGHT edge of the sheet. Include the complete head through feet or footwear; preserve asymmetric clothing.'),
    'body_back': ('full-body back', 'One direct rear full-body neutral standing view. Include the complete head through feet or footwear. No face visible; do not turn the head.'),
    'clothing_front': ('clothing front', 'One front-facing clothing detail of the same character wearing the outfit. Crop from the base of the neck to the complete lowest garment edge. Keep the head outside the frame and retain naturally visible arms and hands.'),
    'clothing_back': ('clothing back', 'One direct rear clothing detail of the same character wearing the outfit. Crop from the base of the neck to the complete lowest garment edge. Keep the head outside the frame and retain naturally visible arms and hands.'),
    'hands': ('hands detail', 'One isolated close-up of exactly two complete hands, one left and one right, cropped at the wrists. No head, torso or whole figure.'),
    'feet': ('feet and footwear detail', 'One isolated close-up of exactly one left and one right complete foot or footwear, including visible boot shafts. Show enclosing shoe surfaces as continuous material, with skin only through existing openings. No head, torso or whole figure.'),
    'helmet_front': ('NEWTECONS safety helmet front', 'One detailed front close-up view of the official white NEWTECONS engineer safety helmet. The red letter N and cyan NEWTECONS brand logo are clearly printed on the front center of the helmet.'),
    'helmet_3q_left': ('NEWTECONS safety helmet left 3/4', 'One anatomical left three-quarter 45-degree view of the official white NEWTECONS engineer safety helmet, showing the side curvature and visor brim.'),
    'helmet_3q_right': ('NEWTECONS safety helmet right 3/4', 'One anatomical right three-quarter 45-degree view of the official white NEWTECONS engineer safety helmet, showing the side curvature and visor brim.'),
    'helmet_side': ('NEWTECONS safety helmet side profile', 'One strict side profile view of the official white NEWTECONS engineer safety helmet showing the ergonomic shell and brim.'),
    'vest_front': ('NEWTECONS reflective vest front', 'One front view of the official NEWTECONS high-visibility engineer reflective safety vest. Silver-grey fabric with fluorescent yellow and reflective stripes, and the NEWTECONS company emblem on the left chest pocket.'),
    'vest_back': ('NEWTECONS reflective vest back', 'One direct rear view of the official NEWTECONS high-visibility engineer reflective safety vest showing wide horizontal reflective bands and the prominent NEWTECONS logo text across the upper back.'),
    'vest_3q': ('NEWTECONS reflective vest 3/4 view', 'One three-quarter perspective view of the official NEWTECONS high-visibility engineer reflective safety vest on a mannequin, displaying front and side reflective stripes.'),
}
