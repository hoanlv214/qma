export type Tier = "preview" | "full";
export type BuyerType = "human" | "agent";

export interface QmaQuery {
  symbol: string;
  fundingRate?: number;
  marketCap?: number;
  FDV?: number;
  circRatio?: number;
  fromATH?: number;
  volume24h?: number;
  amount?: number;
  openInterest?: number;
  openInterestChange24h?: number;
  longShortRatio?: number;
  price?: number;
  [key: string]: unknown;
}

export interface ProviderPricing {
  amount_usdc?: number;
  currency?: string;
}

export interface ProviderSummary {
  provider_id: string;
  provider_name?: string;
  description?: string;
  owner_wallet?: string;
  revenue_wallet?: string;
  enabled?: boolean;
  status?: string;
  pricing?: {
    preview?: ProviderPricing;
    full?: ProviderPricing;
  };
  revenue_share_bps?: number;
  schema?: Record<string, unknown>;
}

export interface SplitLeg {
  leg_id: string;
  role?: string;
  pay_to: string;
  amount_raw: string;
  amount_usdc?: string | number;
  resource: string;
  status?: "pending" | "paid" | string;
  settlement_id?: string;
  sidecar_receipt?: string;
  expires_at?: number;
}

export interface InvoiceRequest extends QmaQuery {
  provider_id?: string;
  tier?: Tier;
  resource_type?: "qma_signal_report" | string;
  buyer_type?: BuyerType;
  synthetic?: boolean;
  agent_label?: string;
  run_source?: string;
}

export interface InvoiceResponse {
  invoice_id: string;
  invoice_secret: string;
  arc_gateway_url: string;
  amount: number;
  tier: Tier;
  tier_label?: string;
  provider_id: string;
  provider_name?: string;
  buyer_type?: BuyerType;
  wallet_address: string;
  network?: string;
  network_name?: string;
  split_legs?: SplitLeg[];
  settlement?: {
    amount?: number;
    currency?: string;
    decimals?: number;
    network?: string;
    rail?: string;
    token_address?: string;
  };
  accounting?: Record<string, unknown>;
}

export interface SplitSettlementProof {
  leg_id: string;
  settlement_id: string;
  pay_to: string;
  amount_raw: string;
  sidecar_receipt: string;
}

export interface PaymentVerifyRequest {
  settlement_id?: string;
  invoice_secret: string;
  payer_address?: string;
  amount_usdc?: number;
  split_settlements?: SplitSettlementProof[];
}

export interface PaymentVerifyResponse {
  status: "paid" | "pending" | string;
  access_token?: string;
  settlement_id?: string;
  gateway_status?: string;
  seller_wallet?: string;
  transaction_hash?: string;
  explorer_url?: string;
}

export interface PaidReport {
  query_symbol?: string;
  query?: QmaQuery;
  query_hash?: string;
  tier?: Tier;
  provider_id?: string;
  provider_name?: string;
  invoice?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface WalletSummary {
  address?: string;
  metrics?: Record<string, unknown>;
  gateway_balance?: {
    available_usdc?: number;
    pending_batch_usdc?: number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}
