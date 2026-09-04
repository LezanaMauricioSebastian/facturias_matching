/**
 * Modo de línea del proceso por cantidad de filas por comprobante:
 * Encabezado (1 línea) XOR con Líneas (>1). No mezclar en el mismo proceso.
 * Con 1 línea: sin pie (montos en la fila). Con varias: pie visible.
 */
import { groupBounds, isFirstRowOfComprobante } from "./groups.js";

/** @typedef {"encabezado" | "lineas" | "mixed" | "empty"} ProcesoLineMode */

/** Cantidad de filas del comprobante que contiene `idx`. */
export function comprobanteLineCount(rows, idx) {
  const [s, e] = groupBounds(rows, idx);
  return Math.max(0, e - s);
}

/** True si el comprobante de `idx` tiene exactamente una fila. */
export function isOneLineComprobante(rows, idx) {
  return comprobanteLineCount(rows, idx) === 1;
}

/**
 * Clasifica el proceso: todos 1 línea → encabezado; todos >1 → lineas; si no → mixed.
 * @param {object[]} rows
 * @returns {ProcesoLineMode}
 */
export function classifyProcesoLineMode(rows) {
  if (!Array.isArray(rows) || !rows.length) return "empty";
  let hasEncabezado = false;
  let hasLineas = false;
  for (let i = 0; i < rows.length; i++) {
    if (!isFirstRowOfComprobante(rows, i)) continue;
    if (comprobanteLineCount(rows, i) <= 1) hasEncabezado = true;
    else hasLineas = true;
    if (hasEncabezado && hasLineas) return "mixed";
  }
  if (hasEncabezado) return "encabezado";
  if (hasLineas) return "lineas";
  return "empty";
}

/** Mensaje si el proceso mezcla comprobantes de 1 línea y de varias. */
export function mixedProcesoLineModeError(rows) {
  if (classifyProcesoLineMode(rows) !== "mixed") return null;
  return (
    "El proceso mezcla comprobantes de 1 línea (Encabezado, sin pie) y con varias líneas. " +
    "Un proceso debe ser solo Encabezado (1 línea) o solo con Líneas (no ambos)."
  );
}
