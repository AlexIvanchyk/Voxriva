import { Input, Select } from "antd";
import { useRef } from "react";

export type Activate = (insert: (value: string) => void) => void;
export function VariableInsert({ variables, insert, disabled }: { variables: string[]; insert: (value: string) => void; disabled: boolean }) {
  return <Select className="variable-insert" aria-label="Insert variable" showSearch placeholder="Insert variable" value={undefined} disabled={disabled || !variables.length} options={variables.map((value) => ({ value, label: `{{ ${value} }}` }))} onChange={(value) => insert(`{{ ${value} }}`)} />;
}
export function TextContent({ label, value, change, variables, disabled, activate, multiline = false }: { label: string; value: string; change: (value: string) => void; variables: string[]; disabled: boolean; activate: Activate; multiline?: boolean }) {
  const root = useRef<HTMLDivElement>(null);
  const state = useRef({ value, change }); state.current = { value, change };
  function insert(text: string) { const input = root.current?.querySelector("[data-content-input]") as HTMLInputElement | HTMLTextAreaElement | null; const content = state.current.value; const start = input?.selectionStart ?? content.length; const end = input?.selectionEnd ?? start; state.current.change(content.slice(0, start)+text+content.slice(end)); requestAnimationFrame(() => { input?.focus(); input?.setSelectionRange(start+text.length, start+text.length); }); }
  return <div className="content-field" ref={root}><div className="section-heading"><label>{label}</label><VariableInsert variables={variables} disabled={disabled} insert={insert} /></div>{multiline ? <Input.TextArea data-content-input="true" aria-label={label} rows={5} value={value} disabled={disabled} onFocus={() => activate(insert)} onChange={(event) => change(event.target.value)} /> : <Input data-content-input="true" aria-label={label} value={value} disabled={disabled} onFocus={() => activate(insert)} onChange={(event) => change(event.target.value)} />}</div>;
}

