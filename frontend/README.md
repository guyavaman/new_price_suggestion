# CRM frontend (Angular 18)

One app with a top navbar for the quote system (new quote from a customer message, quotes list,
quote page with 3 packages, plain-language edit, approve/reject) and the catering CRM: dashboard, drag-and-drop pipeline, deal page (quotes,
timeline, tasks, lead-score reasons, agent conversation), AI conversations inbox with human
takeover, tasks, customers, and the customer-facing chat widget.

```bash
npm install
npm start            # http://localhost:4200, expects the API on http://localhost:8000
```

Backend URL, tenant and API key live in `src/app/core/api.service.ts` (`CONFIG`).
Seed demo data first: `cd ../backend && python -m scripts.seed_crm --reset`.
