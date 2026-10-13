// Mock billing endpoints (NEXT_PUBLIC_API_MOCK=1): the starter catalog and a fictional
// subscription, so the billing, pricing, payout-method and admin billing pages render offline.
import type { BillingOverview, CreditWallet, PayoutMethodsView, Plan, PlansResponse } from "../types";

const json = (data: unknown, status = 200) => Response.json(data, { status });

const PLANS: Plan[] = [
  {
    key: "starter",
    name: "Starter",
    description: "Web translation with the AI quality layer for a small team.",
    modules: ["tms", "ai"],
    prices: { month: { EUR: "49.00", USD: "55.00" }, year: { EUR: "490.00", USD: "550.00" } },
    seat_prices: { month: { EUR: "15.00", USD: "17.00" } },
    included: { word: "50000", ai_unit: "500" },
    overage: { EUR: { word: "0.0150", ai_unit: "0.0400" }, USD: { word: "0.0170", ai_unit: "0.0450" } },
    seats_included: 2,
    max_seats: 10,
    interval: "month",
    custom: false,
    currencies: ["EUR", "USD"],
  },
  {
    key: "team",
    name: "Team",
    description: "Adds project management and the reviewer marketplace.",
    modules: ["tms", "ai", "pm", "community"],
    prices: { month: { EUR: "199.00", USD: "219.00" }, year: { EUR: "1990.00", USD: "2190.00" } },
    seat_prices: { month: { EUR: "19.00", USD: "21.00" } },
    included: { word: "250000", ai_unit: "2500" },
    overage: { EUR: { word: "0.0120", ai_unit: "0.0350" }, USD: { word: "0.0135", ai_unit: "0.0390" } },
    seats_included: 5,
    max_seats: 50,
    interval: "month",
    custom: false,
    currencies: ["EUR", "USD"],
  },
  {
    key: "business",
    name: "Business",
    description: "Adds the engine API, the quality auditor and software strings.",
    modules: ["tms", "ai", "pm", "community", "engine", "auditor", "strings"],
    prices: { month: { EUR: "599.00", USD: "659.00" }, year: { EUR: "5990.00", USD: "6590.00" } },
    seat_prices: { month: { EUR: "25.00", USD: "28.00" } },
    included: { word: "1000000", ai_unit: "10000" },
    overage: { EUR: { word: "0.0090", ai_unit: "0.0300" }, USD: { word: "0.0100", ai_unit: "0.0330" } },
    seats_included: 15,
    max_seats: null,
    interval: "month",
    custom: false,
    currencies: ["EUR", "USD"],
  },
  {
    key: "enterprise",
    name: "Enterprise",
    description: "Every module, contract pricing, invoices with terms, PO and bank transfer.",
    modules: ["tms", "engine", "ai", "pm", "auditor", "strings", "community"],
    prices: {},
    seat_prices: {},
    included: {},
    overage: {},
    seats_included: 50,
    max_seats: null,
    interval: "month",
    custom: true,
    currencies: [],
  },
];

const PACKS = [
  { key: "credits_50", name: "Small", credit_amount: "50.00", price: "50.00", currency: "EUR", valid_days: 365 },
  { key: "credits_200", name: "Medium", credit_amount: "210.00", price: "200.00", currency: "EUR", valid_days: 365 },
];

function overview(): BillingOverview {
  const now = new Date();
  const end = new Date(now.getTime() + 20 * 86400_000).toISOString();
  return {
    subscription: {
      id: "sub_mock",
      plan: "team",
      provider: "paddle",
      provider_subscription_id: "sub_mock_provider",
      status: "active",
      interval: "month",
      currency: "EUR",
      seats: 5,
      current_period_start: now.toISOString(),
      current_period_end: end,
      cancel_at: null,
      canceled_at: null,
    },
    pending: null,
    plan: PLANS[1],
    modules: ["ai", "community", "pm", "tms"],
    seats_used: 3,
    period: now.toISOString().slice(0, 7),
    meters: [
      { unit: "word", used: "182400", included: "250000", overage: "0" },
      { unit: "ai_unit", used: "2710", included: "2500", overage: "210" },
    ],
    platform_fee_percent: "5",
    credits_balance: "40.00",
    currency: "EUR",
    provider: "paddle",
  };
}

export function billingRoute(m: string, p: string[]): Response | null {
  const [a, b, c, d] = p;
  if (a === "billing") {
    if (b === "plans" && m === "GET") {
      const out: PlansResponse = {
        items: PLANS,
        credit_packs: PACKS,
        currencies: ["EUR", "USD"],
        platform_fee: { default_percent: "5", max_percent: "8" },
      };
      return json(out);
    }
    if (b === "subscription" && !c && m === "GET") return json(overview());
    if (b === "credits" && !c && m === "GET") {
      const wallet: CreditWallet = { balance: "40.00", currency: "EUR", lots: [], entries: [], packs: PACKS };
      return json(wallet);
    }
    if (m === "POST") return json({ error: { code: "mock", message: "Checkout is not available in mock mode.", details: {} } }, 422);
  }
  if (a === "reviewer" && b === "payout-methods" && m === "GET") {
    const view: PayoutMethodsView = {
      selected: "sepa",
      effective_threshold: "50.00",
      items: (["payoneer", "paypal", "sepa", "wise"] as const).map((method) => ({
        method,
        status: method === "sepa" ? "active" : "not_set_up",
        onboarding_required: method === "payoneer",
        onboarding_url: null,
        details: (method === "sepa" ? { iban: "DE89...3000", account_holder: "Demo Reviewer" } : {}) as Record<string, string>,
        fields: { payoneer: [], paypal: ["email"], sepa: ["account_holder", "iban", "bic"], wise: ["account_holder", "email", "iban"] }[method],
        minimum_payout: { payoneer: "20.00", paypal: "5.00", sepa: "0.00", wise: "5.00" }[method],
        updated_at: null,
        available: method !== "payoneer",
        selected: method === "sepa",
      })),
    };
    return json(view);
  }
  if (a === "admin" && b === "plans" && m === "GET") {
    return json({
      items: PLANS.map((x, i) => ({ ...x, public: true, active: true, sort: (i + 1) * 10, provider_prices: {} })),
      credit_packs: PACKS,
      providers: { paddle: { configured: false, environment: "sandbox" }, stripe: { configured: false, enabled: false }, manual: { configured: true }, selected: { setting: "auto" } },
    });
  }
  if (a === "admin" && b === "orgs" && c && d === "subscription" && m === "GET") {
    return json({ ...overview(), org_id: c, overrides: { add: [], remove: [] }, payment_terms_days: 14, po_number: "", provider_override: null, history: [] });
  }
  return null;
}
