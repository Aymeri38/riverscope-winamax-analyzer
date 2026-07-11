import { createContext, useContext } from "react";
import type { ImportStatus } from "../types";

export interface SafetyContextValue {
  status: ImportStatus | null;
  loading: boolean;
  error: Error | null;
  safeToAnalyze: boolean;
  refresh: () => void;
}

export const SafetyContext = createContext<SafetyContextValue>({
  status: null,
  loading: true,
  error: null,
  safeToAnalyze: false,
  refresh: () => undefined
});

export function useSafety(): SafetyContextValue {
  return useContext(SafetyContext);
}
