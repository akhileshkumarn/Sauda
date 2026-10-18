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
  const sups = m.suppliers.map((s) => supplierName(s));
  const items = m.lines.length;
  return (
    <div className="stack">
      <div className="rf-permit">
        <section className="rf-pgroup may" aria-labelledby="permit-may">
          <h3 id="permit-may"><span className="badge" aria-hidden><Icon name="check" size={12} stroke={2.5} /></span>Sauda may</h3>
          <ul>
            <li><Icon name="check" size={14} stroke={2.5} /><span className="k">Spend in total, at most</span><span className="v">{rupees(m.budget_paise, true)}</span></li>
            <li><Icon name="check" size={14} stroke={2.5} /><span className="k">Pay per item, at most</span><span className="v">its ceiling</span></li>
            <li><Icon name="check" size={14} stroke={2.5} /><span className="k">Ask for delivery by</span><span className="v">{istDate(m.deliver_by)}</span></li>
            <li className="wide"><Icon name="check" size={14} stroke={2.5} /><span className="k">Talk to {sups.length} {sups.length === 1 ? 'supplier' : 'suppliers'}{items ? ` about ${items} ${items === 1 ? 'item' : 'items'}` : ''}</span><span className="v">{sups.join(', ') || 'None selected'}</span></li>
          </ul>
        </section>
        <section className="rf-pgroup wont" aria-labelledby="permit-wont">
          <h3 id="permit-wont"><span className="badge" aria-hidden><Icon name="x" size={12} stroke={2.5} /></span>Sauda won’t</h3>
          <ul>
            <li><Icon name="x" size={14} stroke={2.5} /><span className="k">Pay an advance over</span><span className="v">{m.max_advance_pct}%</span></li>
            <li><Icon name="x" size={14} stroke={2.5} /><span className="k">Act after</span><span className="v">{ist(m.expires_at)}</span></li>
            <li><Icon name="x" size={14} stroke={2.5} /><span className="k">Pay an unregistered supplier or unknown account</span><span /></li>
            <li><Icon name="x" size={14} stroke={2.5} /><span className="k">Order or pay without your approval</span><span /></li>
          </ul>
        </section>
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
