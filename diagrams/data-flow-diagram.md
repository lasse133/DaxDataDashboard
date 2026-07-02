# DAX 40 Audit Risk Radar Data Flow Diagram

This is a data flow diagram, so the arrows name the data being passed between external entities, processes, and data stores. The labels matter more than the line style.

```mermaid
flowchart LR
    analyst([Audit analyst])
    newsapi[NewsAPI]
    gdelt[GDELT DOC 2.0]
    google[Google News RSS]
    huggingface[Hugging Face Hub\n(FinBERT / BART)]
    yahoo[Yahoo Finance chart API]

    p1([1.0 Request news])
    p2([2.0 Normalize and score])
    p3([3.0 Store and present results])

    d1[(SQLite headline cache)]

    analyst -->|company + reporting period| p1
    analyst -->|selected tickers| yahoo
    analyst -->|clear cached headlines| d1

    p1 -->|news query| newsapi
    p1 -->|history query| google
    p1 -->|debug query| gdelt

    newsapi -->|headline text| p2
    google -->|headline text| p2
    gdelt -->|headline text| p2
    yahoo -->|price ticks| p3

    p2 -->|model inputs| huggingface
    huggingface -->|sentiment scores + risk tags| p2

    p2 -->|scored headlines| d1
    d1 -->|cached headlines| p3

    p3 -->|warnings + charts| analyst
```