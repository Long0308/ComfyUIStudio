"""``jjv video``: pipeline VIDEO theo từng shot (planned -> prompted -> rendered -> upscaled_1080 -> accepted).

Gói này KHÔNG dựng pipeline song song: bước render dùng lại ``engine.h3`` (prepare/submit/adopt/accept + ledger)
và ``engine.comfy.dispatch`` có khoá; nó chỉ thêm trạng thái theo shot, receipt chain, cổng dừng và lịch
"một shot xong 1080p rồi mới sang shot kế".  Mọi dữ liệu theo domain nằm ở ``recipes/video/routes-v001.json``.
"""
