-- depends: 20261012_000001__create_app_settings
-- Home entry points are public, non-secret configuration, not client constants.
-- Edit app_settings.value for key home.tools to publish updates without restarting the API.
-- enabled=false hides an entry; sort_order controls order. Missing copy falls back to zh-Hant.
-- action.type: none (show message), url (HTTPS), route (an already installed app route).
INSERT INTO app_settings (`key`, `value`, description)
VALUES (
    'home.tools',
    '{
      "items": [
        {
          "id": "commute",
          "icon": "train",
          "enabled": true,
          "sort_order": 10,
          "action": {"type": "none", "target": null},
          "translations": {
            "zh-Hans": {
              "title": "港深跨境通勤",
              "description": "口岸过关与公共交通信息",
              "badge": "待接入",
              "message": "此工具尚未开放，完成数据接入后将提供实际信息。"
            },
            "zh-Hant": {
              "title": "港深跨境通勤",
              "description": "口岸過關與公共交通資訊",
              "badge": "待接入",
              "message": "此工具尚未開放，完成數據接入後將提供實際資訊。"
            },
            "yue-Hant-HK": {
              "title": "港深跨境通勤",
              "description": "睇口岸過關同公共交通資訊",
              "badge": "未接入",
              "message": "呢個工具仲未開放，接好數據之後就會有實際資訊。"
            },
            "en": {
              "title": "Cross-border commute",
              "description": "Border crossing and transport updates",
              "badge": "Not connected yet",
              "message": "This tool is not available yet. Live data will appear after integration."
            }
          }
        },
        {
          "id": "residency",
          "icon": "event_note",
          "enabled": true,
          "sort_order": 20,
          "action": {"type": "none", "target": null},
          "translations": {
            "zh-Hans": {
              "title": "永居与续签规划",
              "description": "停留记录与续签提醒",
              "badge": "待接入",
              "message": "此工具尚未开放，完成数据接入后将提供实际信息。"
            },
            "zh-Hant": {
              "title": "永居與續簽規劃",
              "description": "停留記錄與續簽提醒",
              "badge": "待接入",
              "message": "此工具尚未開放，完成數據接入後將提供實際資訊。"
            },
            "yue-Hant-HK": {
              "title": "永居同續簽規劃",
              "description": "記低留港日子，提醒你續簽",
              "badge": "未接入",
              "message": "呢個工具仲未開放，接好數據之後就會有實際資訊。"
            },
            "en": {
              "title": "Residency & visa tracker",
              "description": "Stay records and renewal reminders",
              "badge": "Not connected yet",
              "message": "This tool is not available yet. Live data will appear after integration."
            }
          }
        },
        {
          "id": "education",
          "icon": "school",
          "enabled": true,
          "sort_order": 30,
          "action": {"type": "none", "target": null},
          "translations": {
            "zh-Hans": {
              "title": "香港升学",
              "description": "院校探索与申请规划",
              "badge": "待接入",
              "message": "此工具尚未开放，完成数据接入后将提供实际信息。"
            },
            "zh-Hant": {
              "title": "香港升學",
              "description": "院校探索與申請規劃",
              "badge": "待接入",
              "message": "此工具尚未開放，完成數據接入後將提供實際資訊。"
            },
            "yue-Hant-HK": {
              "title": "香港升學",
              "description": "搵學校同規劃申請",
              "badge": "未接入",
              "message": "呢個工具仲未開放，接好數據之後就會有實際資訊。"
            },
            "en": {
              "title": "Study in Hong Kong",
              "description": "Programme discovery and application planning",
              "badge": "Not connected yet",
              "message": "This tool is not available yet. Live data will appear after integration."
            }
          }
        },
        {
          "id": "business",
          "icon": "storefront",
          "enabled": true,
          "sort_order": 40,
          "action": {"type": "none", "target": null},
          "translations": {
            "zh-Hans": {
              "title": "商业数据",
              "description": "牌照查询、监控与数据导出",
              "badge": "待接入",
              "message": "此工具尚未开放，完成数据接入后将提供实际信息。"
            },
            "zh-Hant": {
              "title": "商業數據",
              "description": "牌照查詢、監控與數據匯出",
              "badge": "待接入",
              "message": "此工具尚未開放，完成數據接入後將提供實際資訊。"
            },
            "yue-Hant-HK": {
              "title": "商業數據",
              "description": "查牌照、追蹤更新同匯出數據",
              "badge": "未接入",
              "message": "呢個工具仲未開放，接好數據之後就會有實際資訊。"
            },
            "en": {
              "title": "Business data",
              "description": "Licence search, monitoring and data export",
              "badge": "Not connected yet",
              "message": "This tool is not available yet. Live data will appear after integration."
            }
          }
        }
      ]
    }',
    'Home tool entries, ordering, visibility, actions and localized copy'
);
