'use client';

/**
 * UI copy for the person pages. Ground truth: design/copy.json (imported directly, never copied), plus
 * lib/copy-web.json for the few web-only keys. Language: ?lang=fi|en → remembered (localStorage kaiku.lang)
 * → browser language → English.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import designCopy from '@design/copy.json';
import webCopy from './copy-web.json';
import { mergeTables, parseLang, translate, type Lang, type Vars } from './copy.ts';

const TABLES = mergeTables(designCopy, webCopy);
const KEY = 'kaiku.lang';

type T = (key: string, vars?: Vars) => string;
interface Ctx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: T;
}

const LangCtx = createContext<Ctx>({ lang: 'en', setLang: () => {}, t: (k, v) => translate(TABLES, 'en', k, v) });

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>('en');
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(KEY);
    } catch {
      /* storage blocked */
    }
    const q = parseLang(new URLSearchParams(window.location.search).get('lang'));
    const l = q ?? parseLang(stored) ?? parseLang(navigator.language) ?? 'en';
    setLangState(l);
  }, []);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      window.localStorage.setItem(KEY, l);
    } catch {
      /* storage blocked */
    }
  }, []);
  const value = useMemo<Ctx>(() => ({ lang, setLang, t: (k, v) => translate(TABLES, lang, k, v) }), [lang, setLang]);
  return <LangCtx.Provider value={value}>{children}</LangCtx.Provider>;
}

export const useCopy = () => useContext(LangCtx);
