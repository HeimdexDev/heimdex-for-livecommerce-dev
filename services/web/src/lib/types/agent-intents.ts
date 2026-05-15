export interface AgentIntentResponse {
  intent_code: string;
  type: string;
  expires_at: string;
  deep_link_url: string;
}

export interface ExchangeIntentResponse {
  type: string;
  org_id: string;
  payload: Record<string, unknown>;
}
