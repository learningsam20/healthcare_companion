import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "sahyog.theme";

interface ThemeValue {
  preference: ThemeMode;
  resolved: "light" | "dark";
  setPreference: (mode: ThemeMode) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeValue | null>(null);

function systemMode(): "light" | "dark" {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function initialPreference(): ThemeMode {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") return stored;
  return "system";
}

function resolve(mode: ThemeMode): "light" | "dark" {
  return mode === "system" ? systemMode() : mode;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemeMode>(initialPreference);
  const [resolved, setResolved] = useState<"light" | "dark">(() => resolve(initialPreference()));

  useEffect(() => {
    const apply = () => {
      const next = resolve(preference);
      setResolved(next);
      document.documentElement.dataset.theme = next;
      document.documentElement.style.colorScheme = next;
    };
    apply();
    localStorage.setItem(STORAGE_KEY, preference);
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = () => {
      if (preference === "system") apply();
    };
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, [preference]);

  const setPreference = useCallback((mode: ThemeMode) => setPreferenceState(mode), []);
  const toggle = useCallback(() => {
    setPreferenceState((current) => {
      const active = resolve(current);
      return active === "dark" ? "light" : "dark";
    });
  }, []);

  const value = useMemo<ThemeValue>(
    () => ({ preference, resolved, setPreference, toggle }),
    [preference, resolved, setPreference, toggle],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}
