# Demo: Supply Chain Gateway

## Overview
This demo implements a supply chain agent connected to APIs through AgentCore Gateway. Three REST APIs are registered as Gateway targets, then a fourth (Quality Inspection) is added dynamically — without changing any agent code. The agent discovers all tools at runtime via the Gateway's MCP endpoint.

## Architecture
- **Gateway:** SimulatedGateway with tool registration and discovery
- **4 targets:** Inventory API, Shipping API, Supplier API, Quality Inspection (added dynamically)
- **Agent:** SupplyChainAgent discovers tools via Gateway and routes queries semantically

## Test Cases (4 queries)
| Query | Expected Tool | Description |
|-------|--------------|-------------|
| Check WIDGET-002 inventory | inventory_api | Inventory lookup |
| Status of SHIP-102 | shipping_api | Shipment tracking |
| List all suppliers | supplier_api | Supplier lookup |
| Quality inspection WIDGET-002 | quality_inspection_api | Dynamically added API |

## Running
```bash
python supply_chain_gateway.py
```

## Key Takeaways
1. **Gateway = plugin architecture** — register APIs, agents discover them
2. **Dynamic discovery** — new API added with zero agent code changes
3. **Semantic tool selection** — agent matches query to tool by description
4. **Gateway vs @tool** — loose coupling vs tight integration tradeoff
