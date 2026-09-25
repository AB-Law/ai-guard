import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FilePenLine, Trash2, Upload } from 'lucide-react'
import { Card } from '../ui/Card'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import * as api from '../../lib/api'
import type { UploadedDoc } from '../../lib/types'

/** Everything for one process's knowledge base — seed docs (read-only, from
 * configs/*.yaml), plain file uploads (immutable: delete + re-upload to
 * change), and custom policies authored right here (editable in place,
 * because we own the exact file shape — see api/main.py's create_policy). */
export function KnowledgeBaseEditor({
  processId,
  processTitle,
  seedDocs,
  uploadedDocs,
}: {
  processId: string
  processTitle: string
  seedDocs: string[]
  uploadedDocs: UploadedDoc[]
}) {
  const client = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [note, setNote] = useState<string | null>(null)
  const [composing, setComposing] = useState(false)
  const [editingPath, setEditingPath] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [draftContent, setDraftContent] = useState('')

  function invalidate() {
    client.invalidateQueries({ queryKey: ['configs'] })
  }

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(file, processId),
    onSuccess: (_res, file) => {
      setNote(`${file.name} indexed into ${processTitle}`)
      invalidate()
    },
    onError: (err: Error) => setNote(err.message),
  })

  const createPolicy = useMutation({
    mutationFn: api.createPolicy,
    onSuccess: () => {
      setNote(`"${draftTitle}" indexed into ${processTitle}`)
      setComposing(false)
      setDraftTitle('')
      setDraftContent('')
      invalidate()
    },
    onError: (err: Error) => setNote(err.message),
  })

  const updatePolicy = useMutation({
    mutationFn: ({ filename, title, content }: { filename: string; title: string; content: string }) =>
      api.updatePolicy(processId, filename, { title, content }),
    onSuccess: () => {
      setNote(`"${draftTitle}" updated`)
      setEditingPath(null)
      invalidate()
    },
    onError: (err: Error) => setNote(err.message),
  })

  const deleteDoc = useMutation({
    mutationFn: (docPath: string) => api.deleteDocument(processId, docPath),
    onSuccess: () => {
      setNote('Document removed from the knowledge base')
      invalidate()
    },
    onError: (err: Error) => setNote(err.message),
  })

  const editingFilename = editingPath?.split('/').pop() ?? ''
  const editingQuery = useQuery({
    queryKey: ['policy', processId, editingFilename],
    queryFn: () => api.getPolicy(processId, editingFilename),
    enabled: !!editingPath,
  })

  function startEdit(doc: UploadedDoc) {
    setComposing(false)
    setEditingPath(doc.path)
    setDraftTitle(doc.name.replace(/\.md$/, ''))
    setDraftContent(editingQuery.data?.content ?? '')
  }

  function handleFiles(files: FileList | null) {
    const file = files?.[0]
    if (file) upload.mutate(file)
  }

  return (
    <Card className="flex flex-col gap-3.5 px-5 py-[18px]">
      <div className="flex items-center justify-between">
        <div className="text-[13px] font-bold text-text-secondary">Knowledge base — {processTitle}</div>
        {!composing && !editingPath && (
          <Button type="button" variant="default" size="sm" onClick={() => setComposing(true)}>
            <FilePenLine size={13} strokeWidth={2} />
            Write a policy
          </Button>
        )}
      </div>

      <button
        onClick={() => fileInput.current?.click()}
        className="flex flex-col items-center gap-2 rounded-xl border-[1.5px] border-dashed border-border px-6 py-[26px] text-text-secondary hover:border-accent hover:text-text-primary"
      >
        <Upload size={22} strokeWidth={1.6} />
        <span className="text-[12.5px] font-semibold">
          {upload.isPending ? 'Uploading…' : 'Drop a .md / .txt / .csv policy document'}
        </span>
        <span className="text-[11.5px] text-text-muted">Indexed into the live KB immediately — no restart</span>
      </button>
      <input
        ref={fileInput}
        type="file"
        accept=".md,.txt,.csv"
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />

      {composing && (
        <div className="flex flex-col gap-2 rounded-lg border border-border-subtle bg-surface-2 p-3.5">
          <Input
            placeholder="Policy title, e.g. Escalation SLA"
            value={draftTitle}
            onChange={(e) => setDraftTitle(e.target.value)}
          />
          <textarea
            placeholder="Write the policy text the gateway and agent should ground against…"
            value={draftContent}
            onChange={(e) => setDraftContent(e.target.value)}
            rows={5}
            className="w-full rounded-lg border border-border bg-surface px-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-accent"
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setComposing(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="accent"
              size="sm"
              disabled={!draftTitle.trim() || !draftContent.trim() || createPolicy.isPending}
              onClick={() => createPolicy.mutate({ process: processId, title: draftTitle, content: draftContent })}
            >
              {createPolicy.isPending ? 'Saving…' : 'Save policy'}
            </Button>
          </div>
        </div>
      )}

      {note && <div className="text-xs text-text-secondary">{note}</div>}

      <div className="flex flex-col gap-1.5">
        {seedDocs.map((doc) => (
          <div key={doc} className="flex items-center justify-between rounded-lg bg-surface-2 px-3 py-2.5 text-[12.5px]">
            <span className="font-mono">{doc}</span>
            <Badge tone="muted">seed</Badge>
          </div>
        ))}
        {uploadedDocs.map((doc) => (
          <div key={doc.path}>
            <div className="flex items-center justify-between gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-[12.5px]">
              <span className="font-mono">{doc.name}</span>
              <div className="flex items-center gap-2">
                <Badge tone={doc.kind === 'custom' ? 'accent' : 'success'}>{doc.kind}</Badge>
                {doc.kind === 'custom' && (
                  <button
                    type="button"
                    onClick={() => startEdit(doc)}
                    className="text-text-muted hover:text-accent"
                    aria-label={`Edit ${doc.name}`}
                  >
                    <FilePenLine size={14} strokeWidth={1.8} />
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => deleteDoc.mutate(doc.path)}
                  disabled={deleteDoc.isPending}
                  className="text-text-muted hover:text-danger"
                  aria-label={`Delete ${doc.name}`}
                >
                  <Trash2 size={14} strokeWidth={1.8} />
                </button>
              </div>
            </div>
            {editingPath === doc.path && (
              <div className="mt-1.5 flex flex-col gap-2 rounded-lg border border-border-subtle bg-surface-2 p-3.5">
                <Input value={draftTitle} onChange={(e) => setDraftTitle(e.target.value)} />
                <textarea
                  value={editingQuery.isLoading ? 'Loading…' : draftContent || editingQuery.data?.content || ''}
                  onChange={(e) => setDraftContent(e.target.value)}
                  rows={5}
                  disabled={editingQuery.isLoading}
                  className="w-full rounded-lg border border-border bg-surface px-3.5 py-2.5 text-sm text-text-primary outline-none focus:border-accent"
                />
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="ghost" size="sm" onClick={() => setEditingPath(null)}>
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    variant="accent"
                    size="sm"
                    disabled={updatePolicy.isPending}
                    onClick={() =>
                      updatePolicy.mutate({
                        filename: doc.name,
                        title: draftTitle,
                        content: draftContent || editingQuery.data?.content || '',
                      })
                    }
                  >
                    {updatePolicy.isPending ? 'Saving…' : 'Save changes'}
                  </Button>
                </div>
              </div>
            )}
          </div>
        ))}
        {seedDocs.length === 0 && uploadedDocs.length === 0 && (
          <div className="text-xs text-text-muted">No documents indexed yet.</div>
        )}
      </div>
    </Card>
  )
}
