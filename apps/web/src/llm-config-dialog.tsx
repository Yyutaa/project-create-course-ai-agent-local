import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, LlmConfigStatus } from "./api";

export function LlmConfigDialog({ status, onClose, onUpdated }: {
  status?: LlmConfigStatus;
  onClose: () => void;
  onUpdated: (next: LlmConfigStatus) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [model, setModel] = useState<LlmConfigStatus["model"]>(status?.model ?? "deepseek-flash");
  const [apiKey, setApiKey] = useState("");
  const saveMutation = useMutation({
    mutationFn: () => api.saveLlmConfig(model, apiKey.trim() || undefined),
    onSuccess: (next) => { onUpdated(next); onClose(); },
  });
  const clearMutation = useMutation({
    mutationFn: api.clearLlmConfig,
    onSuccess: (next) => { onUpdated(next); onClose(); },
  });
  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);
  const busy = saveMutation.isPending || clearMutation.isPending;
  const error = saveMutation.error || clearMutation.error;

  return (
    <dialog ref={dialogRef} className="config-dialog" onClose={onClose} aria-labelledby="config-title">
      <form onSubmit={(event) => { event.preventDefault(); saveMutation.mutate(); }}>
        <h2 id="config-title">配置 DeepSeek</h2>
        <p>API Key 仅保存在当前电脑的系统凭据库。保存不验证额度或网络连接。</p>
        <label>模型
          <select value={model} onChange={(event) => setModel(event.target.value as LlmConfigStatus["model"])}>
            <option value="deepseek-flash">deepseek-flash</option>
            <option value="deepseek-v4-pro">deepseek-v4-pro</option>
          </select>
        </label>
        <label>API Key {status?.configured ? "（留空则保留原 Key）" : ""}
          <input type="password" autoComplete="new-password" value={apiKey}
            required={!status?.configured} maxLength={4096}
            onChange={(event) => setApiKey(event.target.value)} />
        </label>
        <p className="config-hint">修改或清除配置只影响后续模型调用；正在运行的 Run 可能跨配置。</p>
        {error && <p className="notice error" role="alert">{error.message}</p>}
        <div className="config-actions">
          <button type="submit" disabled={busy}>保存配置</button>
          {(status?.configured || status?.error) && <button type="button" disabled={busy}
            className="secondary" onClick={() => clearMutation.mutate()}>清除配置</button>}
          <button type="button" className="secondary" disabled={busy}
            onClick={() => dialogRef.current?.close()}>取消</button>
        </div>
      </form>
    </dialog>
  );
}
