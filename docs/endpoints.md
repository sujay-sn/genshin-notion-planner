# HoYoLAB interactive map endpoints

Captured from the official Teyvat Interactive Map (Asia server, November 2026) and summarized with `tools/har_summary.py`. Credentials, UIDs, device IDs and names are hidden. Long numbers (7+ digits) are hidden too, since UIDs and timestamps look alike. Lists show their length and first item only.

Only the interactive map's own API calls are kept here. Icons, translations, telemetry and login checks from the same capture are left out.

These endpoints are unofficial and undocumented, and they can change with any patch. See `DESIGN.md` section 4.2 for which ones the planner uses.

Common to all calls: query params `app_sn=ys_obc`, `lang=en-us`, `map_id=2` (Teyvat), and header `x-rpc-map_version`.

Left out as UI-only (notices, feedback, badges, share state): `v1/map/get_feedback`, `v1/map/get_guide`, `v1/map/get_map_pageLabel`, `v1/map/get_public_notice`, `v1/map/join_us`, `v1/map/map_anchor/list`, `v1/map/contribution_notify`, `v1/map/map_label_refresh_red_point`, `v1/user/info`.

## Static calls (sg-public-api-static, no login)

### GET sg-public-api-static.hoyolab.com/common/map_user/ys_obc/v1/map/game_item

Planner use: `avatar.list[].labels` and `weapon.list[].labels` are label IDs from `label/tree`, i.e. the map categories for that character's or weapon's farmable materials (specialty, enemies, boss). This is the map's Character Material feature. Some labels have an empty name.

- calls: 1, status: 200
- query: app_sn=ys_obc, lang=en-us, map_id=2
- headers: origin: https://act.hoyolab.com, referer: https://act.hoyolab.com/, x-rpc-lrsag: , x-rpc-map_version: 4.5

Response:
```json
{
  "retcode": "int = 0",
  "message": "str = 'OK'",
  "data": {
    "avatar": {
      "list": [
        "136 items, first:",
        {
          "item_id": "int (8 digits, hidden)",
          "icon": "url = https://act-webstatic.hoyoverse.com/hk4e/e20200928calculate/item_icon/6966dc8c/b7ea76f3f77eec4997dad6576c183939.png",
          "attr": "int = 3",
          "level": "int = 5",
          "labels": [
            "3 items, first:",
            "int = 38"
          ],
          "name": "str = 'Zibai'"
        }
      ],
      "attrs": "icons per element or weapon type, keyed by attr id",
      "update_time": "int (10 digits, hidden)"
    },
    "weapon": {
      "list": [
        "239 items, first:",
        {
          "item_id": "int = 11519",
          "icon": "url = https://act-webstatic.hoyoverse.com/hk4e/e20200928calculate/item_icon/6966dc8c/fa2ac4d5a0238fb674c44670652fc284.png",
          "attr": "int = 1",
          "level": "int = 5",
          "labels": [
            "2 items, first:",
            "int = 740"
          ],
          "name": "str = 'Lightbearing Moonshard'"
        }
      ],
      "attrs": "icons per element or weapon type, keyed by attr id",
      "update_time": "int (10 digits, hidden)"
    }
  }
}
```

### GET sg-public-api-static.hoyolab.com/common/map_user/ys_obc/v1/map/get_area_pageLabel

Planner use: names for the nation IDs used elsewhere (1 Mondstadt, 2 Liyue, 3 Inazuma, 4 Sumeru, 8 Fontaine, 11 Natlan, 13 Nod-Krai, 16 Snezhnaya, plus underground and sea areas).

- calls: 1, status: 200
- query: app_sn=ys_obc, lang=en-us, map_id=2
- headers: origin: https://act.hoyolab.com, referer: https://act.hoyolab.com/, x-rpc-lrsag: , x-rpc-map_version: 4.5

Response:
```json
{
  "retcode": "int = 0",
  "message": "str = 'OK'",
  "data": {
    "list": [
      "14 items, first:",
      {
        "id": "int = 16",
        "name": "str = 'Snezhnaya'",
        "pc_icon_url": "url = https://act-upload.mihoyo.com/ys-map-op/2026/07/24/141047435/5c6e3ef06450491042c8962101719615_5754227879766569070.png",
        "pc_icon_url2": "url = https://act-upload.mihoyo.com/ys-map-op/2026/07/24/141047435/5d2ee49683c54519026d1d91baa8e539_3293608225574037895.png",
        "pc_icon_url3": "url = https://act-upload.mihoyo.com/ys-map-op/2026/07/24/141047435/b93da0c986810394300336a38fdf9b92_7925753390609428162.png",
        "sort": "int = 14",
        "show_tip": "bool = True",
        "tip_stime": "str (13 digits, hidden)",
        "tip_etime": "str (13 digits, hidden)",
        "map_id": "int = 2",
        "l_x": "int = -10038",
        "l_y": "int = -8821",
        "r_x": "int = -5645",
        "r_y": "int = -4454"
      }
    ]
  }
}
```

### GET sg-public-api-static.hoyolab.com/common/map_user/ys_obc/v2/map/label/tree

Planner use: 821 categories in 15 top-level groups (Waypoints, Special Items, Chests, Puzzle Chest, Local Specialties, Experience, Enemies, Inventory / Materials, Fishing, Ores, Animals, Wood, Landmarks, Investigation, Guide). Not visible in the first item below:

- `recommend_route_list` is filled for 57 categories. Each route has `name`, `path_name` (e.g. "Valberry Harvest Routes"), `content` (e.g. "Valberry *19"), `point_cnt_without_trans`, `main_label_id`, and `url`, a share link that opens the map with the route drawn (`share_type=path`). Links come with `lang=zh-cn`.
- `rec_refresh_hour` is set on top-level groups: 72 for Local Specialties, 24 for Enemies.
- `item_id` links 185 categories to game item IDs.

- calls: 1, status: 200
- query: app_sn=ys_obc, lang=en-us, map_id=2
- headers: origin: https://act.hoyolab.com, referer: https://act.hoyolab.com/, x-rpc-lrsag: , x-rpc-map_version: 4.5

Response:
```json
{
  "retcode": "int = 0",
  "message": "str = 'OK'",
  "data": {
    "tree": [
      "15 items, first:",
      {
        "id": "int = 1",
        "name": "str = 'Waypoints'",
        "icon": "str = ''",
        "parent_id": "int = 0",
        "depth": "int = 1",
        "node_type": "int = 1",
        "jump_type": "int = 0",
        "jump_target_id": "int = 0",
        "wiki_jump_url": "str = ''",
        "display_priority": "int = 0",
        "children": [
          "22 items, first:",
          {
            "id": "int = 2",
            "name": "str = 'Statue of The Seven'",
            "icon": "url = https://act-webstatic.hoyoverse.com/map_manage/20240726/c59585d1fabc9c22ad3fcf94e1622aa8_357413506633071859.png",
            "parent_id": "int = 1",
            "depth": "int = 2",
            "node_type": "int = 2",
            "jump_type": "int = 0",
            "jump_target_id": "int = 0",
            "wiki_jump_url": "str = ''",
            "display_priority": "int = 0",
            "children": [],
            "activity_page_label": "int = 27",
            "area_page_label": [],
            "is_all_area": "bool = True",
            "default_show": "bool = False",
            "ch_ext": "str = ''",
            "sort": "int = 0",
            "area_label_list": [],
            "ext_attr_list": [],
            "recommend_route_list": [],
            "point_count": "int = 64",
            "alias_name": "str = '传送点锚点神像'",
            "item_id": "int = 0",
            "rec_refresh_hour": "int = 0",
            "tips": "str = ''"
          }
        ],
        "activity_page_label": "int = 0",
        "area_page_label": [],
        "is_all_area": "bool = False",
        "default_show": "bool = False",
        "ch_ext": "str = ''",
        "sort": "int = 0",
        "area_label_list": [],
        "ext_attr_list": [],
        "recommend_route_list": [],
        "point_count": "int = 0",
        "alias_name": "str = ''",
        "item_id": "int = 0",
        "rec_refresh_hour": "int = 0",
        "tips": "str = 'This category can help to increase exploration progress'"
      }
    ]
  }
}
```

### GET sg-public-api-static.hoyolab.com/common/map_user/ys_obc/v2/map/point_group

Not used by the planner. Underground floors and their overlays.

- calls: 1, status: 200
- query: app_sn=ys_obc, lang=en-us, map_id=2
- headers: origin: https://act.hoyolab.com, referer: https://act.hoyolab.com/, x-rpc-lrsag: , x-rpc-map_version: 4.5

Response:
```json
{
  "retcode": "int = 0",
  "message": "str = 'OK'",
  "data": {
    "list": [
      "210 items, first:",
      {
        "id": "int = 248",
        "map_id": "int = 2",
        "name": "str = ''",
        "g_floor_name": "str = 'Teyvat'",
        "default_floor_index": "int = 0",
        "underground_entrance_x_pos": "float = -3542.49",
        "underground_entrance_y_pos": "int = -7072",
        "floors": [
          "2 items, first:",
          {
            "id": "int = 372",
            "floor_name": "str = 'Abandoned Station_B1'",
            "overlay": {
              "url": "url = https://act-upload.hoyoverse.com/map_manage/20261104/fcda97115fb7b6b22b761033324aabe5_5320628775370409680.png",
              "l_x": "float = -3944.5",
              "l_y": "int = -7382",
              "r_x": "float = -3195.5",
              "r_y": "int = -6774",
              "width": "int = 749",
              "height": "int = 608"
            },
            "point_ids": [
              "1 items, first:",
              "int = 107135"
            ],
            "entrance_ids": [
              "2 items, first:",
              "int = 106342"
            ],
            "floor_name_short": "str = ''",
            "game_layer_ids": [],
            "vertical_space": "int = 0"
          }
        ],
        "provider": "str = ''",
        "weight": "int = 1",
        "g_floor_group_id": "int = 0"
      }
    ]
  }
}
```

### GET sg-public-api-static.hoyolab.com/common/map_user/ys_obc/v3/map/info

Planner use: `detail_v2.map_version` is a hash that changes when the map data updates. Used as the cache key for everything in this section.

- calls: 4, status: 200
- query: app_sn=ys_obc, lang=en-us, map_id=2
- headers: referer: https://act.hoyolab.com/, x-rpc-lrsag: , x-rpc-map_version: 4.5

Response:
```json
{
  "retcode": "int = 0",
  "message": "str = 'OK'",
  "data": {
    "info": {
      "id": "int = 2",
      "name": "str = 'Teyvat Interactive Map'",
      "parent_id": "int = 1",
      "depth": "int = 2",
      "detail": "str (len 13617)",
      "node_type": "int = 2",
      "children": [],
      "icon": "url = https://act-webstatic.hoyoverse.com/map_manage/20261012/191a621844575ee5b8e44035834d051f_3328806497146477608.png",
      "ch_ext": "str = ''",
      "detail_v2": {
        "total_size": [
          "2 items, first:",
          "int = 36864"
        ],
        "padding": [
          "2 items, first:",
          "int = 7625"
        ],
        "origin": [
          "2 items, first:",
          "int = 24207"
        ],
        "map_version": "str = 'bd70cde160dbd523926208d9fa8961a1'",
        "min_zoom": "int = -4",
        "max_zoom": "int = 0",
        "original_map_size": [
          "2 items, first:",
          "int = 21613"
        ]
      }
    }
  }
}
```

### GET sg-public-api-static.hoyolab.com/common/map_user/ys_obc/v3/map/point/list

Not used by the planner (the embedded map shows pins). `label_ids` picks the categories; this capture only requested waypoints.

- calls: 1, status: 200
- query: app_sn=ys_obc, label_ids=1, lang=en-us, map_id=2
- headers: origin: https://act.hoyolab.com, referer: https://act.hoyolab.com/, x-rpc-lrsag: , x-rpc-map_version: 4.5

Response:
```json
{
  "retcode": "int = 0",
  "message": "str = 'OK'",
  "data": {
    "point_list": [
      "846 items, first:",
      {
        "id": "int = 107298",
        "label_id": "int = 3",
        "x_pos": "float = -3692.2386837090635",
        "y_pos": "float = -7297.86758685876",
        "author_name": "str = 'Account Deleted'",
        "ctime": "str = '2026-11-13 10:10:31'",
        "display_state": "int = 1",
        "area_id": "int = 16",
        "ext_attrs": "str = '{}'",
        "ext_attrs_map": {},
        "z_level": "int = 0",
        "icon_sign": "int = 0",
        "point_group": "null"
      }
    ],
    "label_list": [
      "16 items, first:",
      {
        "id": "int = 3",
        "name": "str = 'Teleport Waypoint'",
        "icon": "url = https://act-webstatic.hoyoverse.com/map_manage/20240726/7d650757c10b70cb42189f7fca0c9778_7547860493386240880.png",
        "parent_id": "int = 1",
        "depth": "int = 2",
        "node_type": "int = 2",
        "jump_type": "int = 0",
        "jump_target_id": "int = 0",
        "wiki_jump_url": "str = ''",
        "display_priority": "int = 0",
        "children": [],
        "activity_page_label": "int = 27",
        "area_page_label": [],
        "is_all_area": "bool = True",
        "default_show": "bool = False",
        "ch_ext": "str = ''",
        "sort": "int = 0",
        "area_label_list": [
          "4 items, first:",
          "int = 5"
        ],
        "ext_attr_list": [],
        "recommend_route_list": [],
        "point_count": "int = 0",
        "alias_name": "str = '传送点锚点tp点'",
        "item_id": "int = 0",
        "rec_refresh_hour": "int = 0",
        "tips": "str = ''"
      }
    ]
  }
}
```

## Account calls (sg-public-api, sent with your login cookies)

### GET sg-public-api.hoyolab.com/common/map_user/ys_obc/v1/map/get_game_exploration_rate

Planner use (optional): exploration by nation (`country`) and area, if the embedded map can't show you logged in. Values here are hidden since they're personal.

- calls: 1, status: 200
- query: app_sn=ys_obc, lang=en-us, map_id=2, region=os_asia, uid=<hidden>
- headers: origin: https://act.hoyolab.com, referer: https://act.hoyolab.com/, x-rpc-device_fp: <hidden>, x-rpc-device_id: <hidden>, x-rpc-lrsag: , x-rpc-map_version: 4.5, x-rpc-page: v6.0.2__#/map/2, x-rpc-platform: 4, x-rpc-view_source: 1

Response:
```json
{
  "retcode": "int = 0",
  "message": "str = 'OK'",
  "data": {
    "country": {
      "1": "int",
      "11": "int",
      "13": "int",
      "16": "int",
      "2": "int",
      "3": "int",
      "4": "int",
      "8": "int"
    },
    "area": {
      "<area id>": "int",
      "...": "65 areas in total"
    },
    "beat_percentage": "str",
    "has_default_role": "bool = True",
    "game_role": {
      "uid": "<hidden>",
      "region": "str = 'os_asia'",
      "nick_name": "<hidden>",
      "header_icon": "url = https://act-webstatic.hoyoverse.com/hk4e/e20200928calculate/item_icon/67c7f6c8/3ab350ac512cb6c2de1614d56f3a23f0.png"
    }
  }
}
```

### GET sg-public-api.hoyolab.com/common/map_user/ys_obc/v1/map/list

Not used. Map list with refresh flags.

- calls: 1, status: 200
- query: app_sn=ys_obc, lang=en-us, map_id=2
- headers: origin: https://act.hoyolab.com, referer: https://act.hoyolab.com/, x-rpc-lrsag: , x-rpc-map_version: 4.5

Response:
```json
{
  "retcode": "int = 0",
  "message": "str = 'OK'",
  "data": {
    "list": [
      "4 items, first:",
      {
        "id": "int = 2",
        "is_refresh": "bool = False"
      }
    ],
    "expire_time": "int (10 digits, hidden)",
    "all_map_list": [
      "10 items, first:",
      {
        "id": "int = 1",
        "name": "str = '提瓦特大地图'",
        "parent_id": "int = 0",
        "depth": "int = 1",
        "detail": "str = ''",
        "node_type": "int = 1",
        "children": [],
        "icon": "str = ''",
        "ch_ext": "str = ''",
        "detail_v2": {
          "total_size": [],
          "padding": [],
          "origin": [],
          "map_version": "str = ''",
          "min_zoom": "int = 0",
          "max_zoom": "int = 0",
          "original_map_size": []
        }
      }
    ]
  }
}
```

### GET sg-public-api.hoyolab.com/common/map_user/ys_obc/v1/map/point/mark_map_point_list

Not used yet. Pins you've marked as collected on the map.

- calls: 1, status: 200
- query: app_sn=ys_obc, lang=en-us, map_id=2
- headers: origin: https://act.hoyolab.com, referer: https://act.hoyolab.com/, x-rpc-lrsag: , x-rpc-map_version: 4.5

Response:
```json
{
  "retcode": "int = 0",
  "message": "str = 'OK'",
  "data": {
    "list": []
  }
}
```

### GET sg-public-api.hoyolab.com/common/map_user/ys_obc/v1/map/spot_kind/get_spot_kinds

Not used yet. In-game pin sync. `is_sync: false` means pin sync is off for this account.

- calls: 1, status: 200
- query: app_sn=ys_obc, game_region=os_asia, game_uid=<hidden>, lang=en-us, map_id=2, ts=<hidden>
- headers: origin: https://act.hoyolab.com, referer: https://act.hoyolab.com/, x-rpc-lrsag: , x-rpc-map_version: 4.5

Response:
```json
{
  "retcode": "int = 0",
  "message": "str = 'OK'",
  "data": {
    "list": [
      "4 items, first:",
      {
        "id": "int (7 digits, hidden)",
        "name": "str = ''",
        "icon_id": "int = 103",
        "icon_url": "url = https://webstatic.hoyoverse.com/upload/static-resource/2022/03/01/21cf4cca8df88b21b805b811755a1b2e_1013535646842396278.png",
        "is_game": "int = 2"
      }
    ],
    "is_sync": "bool = False",
    "already_share": "bool = False"
  }
}
```
