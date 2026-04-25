---
name: radar-spatial-inventory
description: Unified skill for radar-based spatial awareness and inventory management. Tracks item locations, stock levels, and monitors user presence for proactive interactions.
version: 2.2.0
author: Antigravity
license: MIT
metadata:
  hermes:
    tags: [Smart-Home, Inventory, Radar, Spatial-Awareness, Proactive-Sensing]
    homepage: http://localhost:8008
prerequisites:
  commands: [curl]
---

# Radar Spatial Inventory System

A comprehensive skill that bridges physical space with digital inventory. It uses LD2450 radar data to provide both real-time presence awareness and high-precision item tracking.

## When to Use

### 1. Spatial Inventory Management
- "Where is the rice box?"
- "What's on my computer desk?"
- "Check the coke stock in the fridge."

### 2. Proactive Presence Sensing
- "OmniSense, notify me if I stay at the computer for too long."
- "What's the status of my study session?"

## Core Capabilities

### A. Inventory Tracking (2D Plane)
- **Zones**: Items are mapped to 12 household zones (Study, Sofa, Fridge, etc.) using `display` and `active` boundary logic.
- **Modes**: Support for `simple` (unit count) and `detailed` (percentage/capacity) tracking.

### B. Proactive Reminders
- **Stay Monitoring**: Detects continuous presence in `STUDY` and `SOFA` zones.
- **Adaptive Thresholds**: Automatically triggers greetings or health suggestions via the voice gateway when duration exceed pre-set thresholds.

## Trigger Rules & API Reference

### Inventory Operations
| Action | Method | Endpoint | Example Command |
| :--- | :--- | :--- | :--- |
| **List All Items** | `GET` | `/api/inventory` | `curl -s http://localhost:8008/api/inventory` |
| **Add New Item** | `POST` | `/api/inventory` | See examples below |
| **Update Item** | `PUT` | `/api/inventory/{id}`| Syncs coords for all group members if `groupId` exists. |
| **List Groups** | `GET` | `/api/groups` | Get metadata (names) for manual groups. |
| **Update Group** | `PUT` | `/api/groups/{gid}` | Rename or update group metadata. |

#### Creating New Items (POST)
**Simple Mode** (unit count):
```bash
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"name":"橄榄油","remaining":2,"x":0.29,"y":7.6,"zone":"KITCHEN","type":"simple"}' \
  http://localhost:8008/api/inventory
```

**Detailed Mode** (percentage/capacity):
```bash
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"name":"袋装大米","remaining":1,"x":0.31,"y":7.8,"sub_items":[{"r":30,"t":100}],"zone":"KITCHEN","type":"detailed"}' \
  http://localhost:8008/api/inventory
```

| Field | Required | Description |
| :--- | :--- | :--- |
| `name` | Yes | Item name |
| `remaining` | Yes | Count or 1 for detailed |
| `x`, `y` | Yes | 2D coordinates in meters |
| `zone` | Yes | Zone code (e.g. `KITCHEN`, `FRIDGE`) |
| `type` | Yes | `simple` or `detailed` |
| `groupId` | No | ID of an existing group to link this item to |
| `sub_items` | Conditional | Array of `{r, t, u}` for detailed mode |

> [!IMPORTANT]
> **ID Generation**: DO NOT provide an `id` field when creating new items. The server will automatically generate a unique millisecond-precision ID. Providing a manual ID may cause conflicts.

## Explicit Grouping System
The system has moved from automatic proximity clustering to **Explicit Manual Grouping**. 
- **Grouping**: Items are linked via a shared `groupId`. 
- **Syncing**: Updating the (X, Y) coordinates of one item in a group automatically propagates to all other members, ensuring they stay stacked in the spatial UI.
- **Naming**: Groups can have custom names (e.g., "Fridge Top Shelf") stored in the group metadata.
- **AI Guidance**: When an item has a `groupId`, the AI should call `GET /api/groups` to retrieve the human-readable group name for better context in responses.

## Error Handling
- **404 Not Found**: Returns `{"error": "Item not found"}` if the ID is invalid.
- **503 Service Error**: Check if the `omnisense_radar_station` Docker container is running.


## Example Interaction
**User**: "电脑桌上还剩下什么？"
**Assistant**: "检索到[电脑桌杂物]分组，包含一瓶矿泉水和一盒抽纸。同时检测到您已连续在此办公 45 分钟，建议起身活动一下。"
