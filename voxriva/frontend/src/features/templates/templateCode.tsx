import MonacoEditor, { loader } from "@monaco-editor/react";
import { Button, Modal, Skeleton, Space } from "antd";
import "monaco-editor/esm/vs/basic-languages/html/html.contribution";
import "monaco-editor/esm/vs/editor/editor.all";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import HtmlWorker from "monaco-editor/esm/vs/language/html/html.worker?worker";
import "monaco-editor/esm/vs/language/html/monaco.contribution";
import JsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import "monaco-editor/esm/vs/language/json/monaco.contribution";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Activate } from "./templateInputs";
import { VariableInsert } from "./templateInputs";
export { TextContent } from "./templateInputs";
export type { Activate } from "./templateInputs";

self.MonacoEnvironment = { getWorker: (_: string, label: string) => label === "json" ? new JsonWorker() : label === "html" ? new HtmlWorker() : new EditorWorker() };
loader.config({ monaco });
export interface Diagnostic { severity: "warning" | "error"; field: string; line: number; code: string; name?: string; message: string; path?: (string | number)[] }
export function Code({ label, value, onChange, language = "json", readOnly = false, height = 400, variables = [], diagnostics = [], activate, insertImage }: {
  label: string; value: string; onChange: (value: string) => void; language?: string; readOnly?: boolean; height?: number; variables?: string[]; diagnostics?: Diagnostic[]; activate?: Activate; insertImage?: (insert: (value: string) => void) => ReactNode;
}) {
  const [full, setFull] = useState(false);
  const [ready, setReady] = useState(0);
  const editor = useRef<monaco.editor.IStandaloneCodeEditor>();
  const cleanups = useRef<monaco.IDisposable[]>([]);
  const state = useRef({ variables, diagnostics, onChange, activate });
  state.current = { variables, diagnostics, onChange, activate };
  useEffect(() => () => { cleanups.current.forEach((value) => value.dispose()); }, []);
  useEffect(() => { const model = editor.current?.getModel(); if (model && !model.isDisposed()) monaco.editor.setModelMarkers(model, "template-authoring", diagnostics.map((note) => ({ message: note.message, severity: note.severity === "error" ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning, startLineNumber: Math.min(note.line || 1, model.getLineCount()), endLineNumber: Math.min(note.line || 1, model.getLineCount()), startColumn: 1, endColumn: model.getLineMaxColumn(Math.min(note.line || 1, model.getLineCount())) }))); }, [diagnostics, ready]);
  function insert(text: string) { const instance = editor.current; if (!instance || readOnly) return; instance.focus(); const selection = instance.getSelection(); if (selection) instance.executeEdits("insert-variable", [{ range: selection, text, forceMoveMarkers: true }]); }
  function body(editorHeight: number | string) { return <div className="template-code"><div className="code-toolbar"><label>{label}</label><Space wrap>{!readOnly && language === "html" && insertImage?.(insert)}{language !== "json" && <VariableInsert variables={variables} disabled={readOnly} insert={insert} />}{language !== "plaintext" && <Button size="small" disabled={readOnly} onClick={() => void editor.current?.getAction("editor.action.formatDocument")?.run()}>Format code</Button>}<Button size="small" onClick={() => setFull(!full)}>{full ? "Exit full screen" : "Full screen"}</Button></Space></div>
    <MonacoEditor height={editorHeight} language={language} value={value} onChange={(value) => state.current.onChange(value ?? "")} loading={<Skeleton active />} options={{ readOnly, minimap: { enabled: false }, fontSize: 13, wordWrap: "on", scrollBeyondLastLine: false, automaticLayout: true, ariaLabel: label, tabSize: 2, autoClosingBrackets: "never", autoClosingQuotes: "never", autoSurround: "never", padding: { top: 14 } }} onMount={(instance) => {
      cleanups.current.forEach((value) => value.dispose()); cleanups.current = []; editor.current = instance; setReady((value) => value+1);
      cleanups.current.push(instance.onDidFocusEditorText(() => state.current.activate?.(insert)));
      if (language !== "json") cleanups.current.push(monaco.languages.registerCompletionItemProvider(language, { triggerCharacters: ["{", " "], provideCompletionItems: (model, position) => {
        if (model !== instance.getModel()) return { suggestions: [] };
        const word = model.getWordUntilPosition(position); const prefix = model.getLineContent(position.lineNumber).slice(0, position.column-1); const inside = prefix.lastIndexOf("{{") > prefix.lastIndexOf("}}");
        return { suggestions: state.current.variables.map((name) => ({ label: name, kind: monaco.languages.CompletionItemKind.Variable, insertText: inside ? name : `{{ ${name} }}`, range: new monaco.Range(position.lineNumber, word.startColumn, position.lineNumber, word.endColumn), detail: "Template variable" })) };
      } }));
    }} /></div>; }
  return <>{!full && body(height)}{full && <Modal open width="calc(100vw - 40px)" style={{ top: 20 }} title={label} footer={null} onCancel={() => setFull(false)} destroyOnClose>{body("calc(100dvh - 180px)")}</Modal>}</>;
}
