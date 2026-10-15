import { appConfig } from "../config/app";

export const GENLAYER_CONTRACT_ADDRESS =
  import.meta.env.VITE_GENLAYER_CONTRACT_ADDRESS ||
  appConfig.genlayer.contractAddress;

export const GENLAYER_STUDIO_URL =
  import.meta.env.VITE_GENLAYER_STUDIO_URL || appConfig.genlayer.studioUrl;

export const GENLAYER_EXPLORER_URL =
  import.meta.env.VITE_GENLAYER_EXPLORER_URL || appConfig.genlayer.explorerUrl;
