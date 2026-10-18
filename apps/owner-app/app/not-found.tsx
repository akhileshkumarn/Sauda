import { ButtonLink, EmptyState } from '@/components/ui';
export default function NotFound() {
  return (
    <div className="narrow">
      <EmptyState icon="info" title="Page not found" action={<ButtonLink href="/">Go to home</ButtonLink>}>This link does not lead anywhere in Sauda.</EmptyState>
    </div>
  );
}
