import { redirect } from 'next/navigation';

/** /trust has no page of its own: send people to the latest signed record. */
export default function TrustIndex() {
  redirect('/trust/latest');
}
