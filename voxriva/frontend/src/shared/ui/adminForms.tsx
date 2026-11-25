import { DeleteOutlined } from "@ant-design/icons";
import { Alert, Button, Form, Input, Modal, Popconfirm, message } from "antd";
import type { ReactNode } from "react";
import { useId, useState } from "react";
import { errorMessage } from "../api/client";

export function Editor<T extends object>({ title, close, submit, initial, children, description, submitDisabled = false, onValuesChange, submitLabel = "Save" }: {
  title: string;
  close: () => void;
  submit: (values: T) => Promise<void>;
  initial?: Partial<T>;
  submitLabel?: string;
  description?: string;
  submitDisabled?: boolean;
  onValuesChange?: (changed: Partial<T>, values: T) => void;
  children: ReactNode;
}) {
  const formId = `resource-form-${useId().replaceAll(":", "")}`;
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  return <Modal open centered width={600} className="resource-dialog" title={<div className="resource-dialog-heading"><h2>{title}</h2></div>} styles={{ body: { maxHeight: "calc(100dvh - 240px)", overflowY: "auto", paddingRight: 4 } }}
    footer={<div className="editor-actions"><Button size="large" onClick={close} disabled={pending}>Cancel</Button>
      <Button size="large" type="primary" htmlType="submit" form={formId} loading={pending} disabled={submitDisabled}>{submitLabel}</Button></div>} onCancel={close} closable={!pending} maskClosable={!pending}
    keyboard={!pending} destroyOnHidden>
    {description && <p className="resource-dialog-description">{description}</p>}
    {error && <Alert type="error" showIcon message={error} />}
    <Form<T> id={formId} layout="vertical" size="large" initialValues={initial} onValuesChange={onValuesChange} requiredMark={false} onFinish={async (values) => {
      setError("");
      setPending(true);
      try {
        await submit(values);
        close();
      } catch (error) {
        setError(errorMessage(error));
      } finally {
        setPending(false);
      }
    }}>
      {children}
    </Form>
  </Modal>;
}

export function NameField({ placeholder = "Enter a name" }: { placeholder?: string }) {
  return <Form.Item name="name" label="Name" rules={[{ required: true, whitespace: true, max: 100 }]}>
    <Input maxLength={100} placeholder={placeholder} autoFocus />
  </Form.Item>;
}

export function DeleteAction({ title, text, onConfirm, compact = false }: { title: string; text: string; onConfirm: () => Promise<void>; compact?: boolean }) {
  const [feedback, holder] = message.useMessage();
  return <>
    {holder}
    <Popconfirm title={title} description={text} okText="Confirm" okButtonProps={{ danger: true }}
      onConfirm={async () => {
        try { await onConfirm(); }
        catch (error) { void feedback.error(errorMessage(error)); }
      }}>
      <Button danger type={compact ? "text" : "default"} size={compact ? "small" : "middle"}
        icon={compact ? undefined : <DeleteOutlined aria-hidden="true" />}>{title}</Button>
    </Popconfirm>
  </>;
}
