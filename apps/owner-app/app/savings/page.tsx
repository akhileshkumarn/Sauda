import { redirect } from 'next/navigation';
import { SHOP_ID } from '@/lib/api';

/** /savings has no page of its own: send people to this shop's savings. */
export default function SavingsIndex() {
  redirect(`/savings/${SHOP_ID}`);
}
