# Lesson 5: Implementing Routing in Multi-Agent Systems

This lesson teaches how to build a hybrid routing system that combines rule-based routing (fast, free, deterministic) with LLM-powered classification (flexible, handles ambiguity), plus priority routing for business-critical requests and a fallback safety net.

## Folder Structure

```
lesson-5-routing/
├── README.md
├── demo-financial-router/
│   └── solution/
│       ├── README.md
│       └── financial_router.py
└── exercise-telecom-router/
    ├── solution/
    │   ├── README.md
    │   └── telecom_router.py
    └── starter/
        ├── README.md
        └── telecom_router.py
```

## Demo: Hybrid Router for Financial Transactions (Instructor-led)
- **Domain:** Financial services (wire transfers, fraud reports, account inquiries)
- **Architecture:** 5 specialist agents + 1 LLM classifier agent, Python hybrid router
- **Routing strategies:** Priority (>$10K → SeniorReviewAgent), Rule-based (keywords), LLM classification (ambiguous), Fallback (low confidence)
- **Test cases:** 10 requests covering all 4 routing paths
- **Key insight:** Rules first, LLM second saves 70-80% of classification API costs

## Exercise: Multi-Strategy Router for Telecom Tickets (Student-led)
- **Domain:** Telecom support (billing, technical, cancellation)
- **Architecture:** 4 specialist agents + 1 LLM classifier, same hybrid router pattern
- **Routing strategies:** Priority (cancellation → RetentionAgent), Rule-based (billing/technical keywords), LLM classification, Fallback
- **Test cases:** 20 tickets (40% billing, 30% technical, 10% cancellation, 20% ambiguous)
- **Key insight:** Same hybrid pattern, different domain — routing effectiveness report with accuracy, latency, and distribution metrics
