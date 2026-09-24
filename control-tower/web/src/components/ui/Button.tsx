import type { ButtonHTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'

const buttonStyles = cva(
  'inline-flex items-center justify-center gap-1.5 rounded-lg font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed',
  {
    variants: {
      variant: {
        default: 'border border-border bg-surface-2 text-text-primary hover:bg-surface-hover',
        accent: 'border border-accent bg-accent text-[#08111f] hover:bg-[#7fbaff]',
        ghost: 'border border-transparent text-text-secondary hover:bg-surface-hover hover:text-text-primary',
        'danger-outline': 'border border-danger/40 text-danger bg-transparent hover:bg-danger-soft',
        'success-outline': 'border border-success/40 text-success bg-transparent hover:bg-success-soft',
      },
      size: {
        sm: 'px-3 py-1.5 text-xs',
        md: 'px-3.5 py-2 text-[12.5px]',
        lg: 'px-4 py-2.5 text-sm',
      },
    },
    defaultVariants: { variant: 'default', size: 'md' },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonStyles> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonStyles({ variant, size }), className)} {...props} />
}
