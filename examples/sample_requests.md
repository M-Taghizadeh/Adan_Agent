# Example Requests

Base URL: `http://localhost:8000`

## Health

```bash
curl http://localhost:8000/health
```

## RAG — in-scope

```bash
curl -s http://localhost:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"How many days do customers have to return unused products?\",\"force_route\":\"rag\"}"
```

```bash
curl -s http://localhost:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"How many paid annual leave days do full-time employees get?\",\"force_route\":\"rag\"}"
```

## RAG — out of scope (should refuse to invent)

```bash
curl -s http://localhost:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"What is the CEO salary and private phone number?\",\"force_route\":\"rag\"}"
```

## NL2SQL — aggregation / filter / join

```bash
curl -s http://localhost:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"What is the total revenue from all sales?\",\"force_route\":\"sql\"}"
```

```bash
curl -s http://localhost:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"List Electronics products with stock below 150 units\",\"force_route\":\"sql\"}"
```

```bash
curl -s http://localhost:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"Show total revenue by category for sales in Tehran\",\"force_route\":\"sql\"}"
```

## Hybrid (SQL + Calculator)

```bash
curl -s http://localhost:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"What is the total sales revenue and calculate 15 percent of that amount?\",\"force_route\":\"hybrid\"}"
```

## Hybrid, multi-step (several SQL calls + calculator)

```bash
curl -s http://localhost:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"How much more percent revenue did Tehran make than Isfahan?\",\"force_route\":\"hybrid\"}"
```

Look at `tool_calls` and `trace` in the response to see each tool the LLM called.


## Dangerous / invalid SQL (demo endpoint)

```bash
curl -s -X POST "http://localhost:8000/sql/validate?sql=DROP%20TABLE%20products"
```

```bash
curl -s -X POST "http://localhost:8000/sql/validate?sql=DELETE%20FROM%20sales"
```
