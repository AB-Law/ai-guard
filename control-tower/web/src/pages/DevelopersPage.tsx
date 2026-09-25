import { isValidElement, useEffect, useRef, useState, type ComponentProps, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import Markdown, { type Components, type ExtraProps } from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import { Check, Copy } from 'lucide-react'
import readme from '../../../sdk/aiguard/README.md?raw'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { Badge } from '../components/ui/Badge'
import { Button, buttonStyles } from '../components/ui/Button'
import { cn } from '../lib/utils'

type Section = { id: string; label: string }

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function textContent(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textContent).join('')
  if (isValidElement<{ children?: ReactNode }>(node)) return textContent(node.props.children)
  return ''
}

function readmeSections(markdown: string): Section[] {
  return [...markdown.matchAll(/^## (.+)$/gm)].map((match) => {
    const label = match[1].replace(/`/g, '').trim()
    return { id: slugify(label), label }
  })
}

const sections = readmeSections(readme)

function withoutNode<T extends ExtraProps>(props: T): Omit<T, 'node'> {
  const copy = { ...props }
  delete copy.node
  return copy
}

function CodeBlock({ children, ...props }: ComponentProps<'pre'> & ExtraProps) {
  const [copied, setCopied] = useState(false)
  const text = textContent(children)

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="relative my-3">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-label={copied ? 'Copied' : 'Copy code'}
        className="absolute right-2 top-2 px-2"
        onClick={() => void copy()}
      >
        {copied ? <Check size={14} strokeWidth={1.8} /> : <Copy size={14} strokeWidth={1.8} />}
      </Button>
      <pre
        {...withoutNode(props)}
        className="overflow-x-auto rounded-lg border border-border-subtle bg-bg px-3.5 py-3 pr-12 font-mono text-[12px] leading-relaxed text-text-secondary"
      >
        {children}
      </pre>
    </div>
  )
}

function InlineOrBlockCode({ className, children, ...props }: ComponentProps<'code'> & ExtraProps) {
  const highlighted = Boolean(className?.includes('hljs') || className?.includes('language-'))
  if (highlighted) {
    return (
      <code {...withoutNode(props)} className={cn('font-mono', className)}>
        {children}
      </code>
    )
  }
  return (
    <code
      {...withoutNode(props)}
      className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[12px] text-accent"
    >
      {children}
    </code>
  )
}

function heading(tag: 'h1' | 'h2' | 'h3', className: string) {
  return function Heading({ children, ...props }: ComponentProps<'h2'> & ExtraProps) {
    const Tag = tag
    const id = tag === 'h2' ? slugify(textContent(children)) : undefined
    return (
      <Tag {...withoutNode(props)} id={id} className={className}>
        {children}
      </Tag>
    )
  }
}

const markdownComponents: Components = {
  h1: heading('h1', 'mb-3 text-[18px] font-bold text-text-primary'),
  h2: heading('h2', 'mb-2 mt-8 scroll-mt-16 text-[15px] font-bold text-text-primary'),
  p: ({ children, ...props }) => (
    <p {...withoutNode(props)} className="mb-3 text-[13px] leading-relaxed text-text-secondary">
      {children}
    </p>
  ),
  a: ({ children, ...props }) => (
    <a {...withoutNode(props)} className="font-semibold text-accent">
      {children}
    </a>
  ),
  strong: ({ children, ...props }) => (
    <strong {...withoutNode(props)} className="font-bold text-text-primary">
      {children}
    </strong>
  ),
  pre: CodeBlock,
  code: InlineOrBlockCode,
}

export function DevelopersPage() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [activeId, setActiveId] = useState(sections[0]?.id ?? '')

  useEffect(() => {
    const root = scrollRef.current
    if (!root || typeof IntersectionObserver === 'undefined') return
    const nodes = sections
      .map((section) => document.getElementById(section.id))
      .filter((node): node is HTMLElement => node != null)
    if (nodes.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (visible?.target.id) setActiveId(visible.target.id)
      },
      { root, rootMargin: '-10% 0px -70% 0px', threshold: [0, 0.25, 0.5, 1] },
    )
    nodes.forEach((node) => observer.observe(node))
    return () => observer.disconnect()
  }, [])

  function jump(id: string) {
    setActiveId(id)
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <>
      <style>{HIGHLIGHT_CSS}</style>
      <PageHeader
        title="Developers"
        subtitle="SDK guide for integrating an agent with this control tower"
        showProcessSwitcher={false}
      />

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8 lg:py-[26px]">
        <Card className="mb-6 flex flex-col gap-3 px-5 py-[18px]">
          <Badge tone="accent" className="self-start">
            Get started
          </Badge>
          <p className="max-w-3xl text-[13px] leading-relaxed text-text-secondary">
            Create an application to get a real API key, then point the aiguard client at this tower.
            The guide below is the SDK README — install, configure, and wire the plain-Python decorator
            or a LangChain integration from the same source the package ships with.
          </p>
          <Link to="/applications" className={cn(buttonStyles({ variant: 'accent' }), 'self-start')}>
            Get an API key
          </Link>
        </Card>

        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          <nav
            aria-label="On this page"
            className="sticky top-0 z-10 flex gap-1 overflow-x-auto border-b border-border bg-bg py-2 lg:w-56 lg:shrink-0 lg:flex-col lg:gap-0.5 lg:overflow-visible lg:border-0 lg:bg-transparent lg:py-0"
          >
            {sections.map((section) => (
              <button
                key={section.id}
                type="button"
                onClick={() => jump(section.id)}
                className={cn(
                  'shrink-0 rounded-lg px-3 py-2 text-left text-[13px] font-medium whitespace-nowrap text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary lg:whitespace-normal',
                  activeId === section.id && 'bg-accent-soft text-accent',
                )}
              >
                {section.label}
              </button>
            ))}
          </nav>

          <article className="dev-docs min-w-0 flex-1">
            <Markdown rehypePlugins={[rehypeHighlight]} components={markdownComponents}>
              {readme}
            </Markdown>
          </article>
        </div>
      </div>
    </>
  )
}

const HIGHLIGHT_CSS = `
.dev-docs .hljs-keyword,
.dev-docs .hljs-built_in,
.dev-docs .hljs-type,
.dev-docs .hljs-selector-tag { color: var(--color-accent); }
.dev-docs .hljs-string,
.dev-docs .hljs-attr { color: var(--color-success); }
.dev-docs .hljs-number,
.dev-docs .hljs-literal { color: var(--color-warning); }
.dev-docs .hljs-comment,
.dev-docs .hljs-doctag { color: var(--color-text-muted); }
.dev-docs .hljs-title,
.dev-docs .hljs-title.function_,
.dev-docs .hljs-function { color: var(--color-text-primary); }
.dev-docs .hljs-params,
.dev-docs .hljs-punctuation,
.dev-docs .hljs-operator,
.dev-docs .hljs-variable { color: var(--color-text-secondary); }
`
