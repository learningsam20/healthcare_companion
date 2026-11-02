import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  dictionaries,
  isLocale,
  localeNames,
  type Locale,
  type TranslationKey,
} from "../i18n/locales";

const STORAGE_KEY = "sahyog.locale";

interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
  locales: { code: Locale; label: string }[];
}

const I18nContext = createContext<I18nValue | null>(null);

function initialLocale(): Locale {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (isLocale(stored)) return stored;
  const configured = (import.meta.env.VITE_DEFAULT_LOCALE as string | undefined) ?? "";
  if (isLocale(configured)) return configured;
  const browser = navigator.language;
  if (browser.startsWith("hi")) return "hi-IN";
  if (browser.startsWith("mr")) return "mr-IN";
  return "en-IN";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
    localStorage.setItem(STORAGE_KEY, locale);
  }, [locale]);

  const setLocale = useCallback((next: Locale) => setLocaleState(next), []);

  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => {
      const dictionary = dictionaries[locale] as Record<string, string>;
      let text = dictionary[key] ?? dictionaries["en-IN"][key] ?? key;
      if (vars) {
        for (const [name, value] of Object.entries(vars)) {
          text = text.split(`{${name}}`).join(String(value));
        }
      }
      return text;
    },
    [locale],
  );

  const value = useMemo<I18nValue>(
    () => ({
      locale,
      setLocale,
      t,
      locales: Object.keys(localeNames).map((code) => ({
        code: code as Locale,
        label: localeNames[code],
      })),
    }),
    [locale, setLocale, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}
