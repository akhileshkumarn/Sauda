// The plain "Sauda MAY / MAY NOT" summary of a mandate. Used before signing and on the signed mandate.
import { cap1, ceilingSource, ist, istDate, rupees, supplierName } from '@/lib/format';
import { Evidence, Icon } from './ui';

export interface PermissionsInput {
  budget_paise: number;
  suppliers: string[];
  lines: { gtin: string; name?: string; qty: number; ceiling_paise: number; ceiling_source?: string }[];
  max_advance_pct: number;
  deliver_by: string;
  expires_at: string;
}

export function Permissions({ m, showLines = true }: { m: PermissionsInput; showLines?: boolean }) {
  const n = m.suppliers.length;
  return (
    <div className="stack">
      <div className="permit">
        <div className="permit-col may">
          <h3><Icon name="check" size={18} stroke={2.5} />Sauda may…</h3>
          <ul>
            <li><Icon name="check" size={14} stroke={3} /><span>Talk to <b>{m.suppliers.map((s) => supplierName(s)).join(', ') || 'none selected'}</b></span></li>
            <li><Icon name="check" size={14} stroke={3} /><span>Spend up to <b className="num">{rupees(m.budget_paise, true)}</b> in total</span></li>
            <li><Icon name="check" size={14} stroke={3} /><span>Pay up to each item’s ceiling ({m.lines.length} {m.lines.length === 1 ? 'item' : 'items'})</span></li>
            <li><Icon name="check" size={14} stroke={3} /><span>Ask for delivery by <b>{istDate(m.deliver_by)}</b></span></li>
          </ul>
        </div>
        <div className="permit-col maynot">
          <h3><Icon name="x" size={18} stroke={2.5} />Sauda won’t…</h3>
          <ul>
            <li><Icon name="x" size={14} stroke={3} /><span>Pay an advance over <b>{m.max_advance_pct}%</b></span></li>
            <li><Icon name="x" size={14} stroke={3} /><span>Pay an unregistered supplier or unknown account</span></li>
            <li><Icon name="x" size={14} stroke={3} /><span>Order or pay without your approval</span></li>
            <li><Icon name="x" size={14} stroke={3} /><span>Act after <b>{ist(m.expires_at)}</b></span></li>
          </ul>
        </div>
      </div>
      {showLines && m.lines.length > 0 && (
        <Evidence label={`Item ceilings · ${m.lines.length}`}><div className="table-wrap">
          <table>
            <caption className="sr-only">Item ceilings</caption>
            <thead><tr><th>Item</th><th className="right">Qty</th><th className="right">Ceiling / unit</th></tr></thead>
            <tbody>
              {m.lines.map((l) => (
                <tr key={l.gtin}>
                  <td><div className="small strong break">{cap1(l.name) || `Item ${l.gtin}`}</div>{l.ceiling_source && <div className="xs faint">{ceilingSource(l.ceiling_source)}</div>}</td>
                  <td className="right num">{l.qty.toLocaleString('en-IN')}</td>
                  <td className="right num">{rupees(l.ceiling_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div></Evidence>
      )}
      <p className="xs faint">Ceiling = most Sauda may pay per unit.</p>
    </div>
  );
}
