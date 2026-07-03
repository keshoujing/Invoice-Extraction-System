import { useCallback, useEffect, useState } from "react";
import {
  assignSupplierScheme,
  clearSupplierScheme,
  createSupplier as apiCreateSupplier,
  deleteSupplier as apiDeleteSupplier,
  listSuppliers,
  listSupplierSchemeMap
} from "../api";
import type { Supplier } from "../types";

export function useSuppliers() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [map, setMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextSuppliers, nextMap] = await Promise.all([
        listSuppliers("", 5000),
        listSupplierSchemeMap()
      ]);
      setSuppliers([...nextSuppliers].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })));
      setMap(nextMap);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const createSupplier = useCallback(async (code: string, name: string) => {
    setWorking(true);
    try {
      await apiCreateSupplier({ code, name });
      await refresh();
    } finally {
      setWorking(false);
    }
  }, [refresh]);

  const deleteSupplier = useCallback(async (code: string) => {
    setWorking(true);
    try {
      await apiDeleteSupplier(code);
      await refresh();
    } finally {
      setWorking(false);
    }
  }, [refresh]);

  const assignScheme = useCallback(async (code: string, schemeName: string) => {
    setWorking(true);
    try {
      await assignSupplierScheme(code, schemeName);
      setMap((previous) => ({ ...previous, [code]: schemeName }));
    } finally {
      setWorking(false);
    }
  }, []);

  const clearScheme = useCallback(async (code: string) => {
    setWorking(true);
    try {
      await clearSupplierScheme(code);
      setMap((previous) => {
        const next = { ...previous };
        delete next[code];
        return next;
      });
    } finally {
      setWorking(false);
    }
  }, []);

  return {
    suppliers,
    map,
    loading,
    working,
    refresh,
    createSupplier,
    deleteSupplier,
    assignScheme,
    clearScheme
  };
}
