import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="not-found">
      <span>404</span>
      <h1>Cette page n’existe pas</h1>
      <p>Le lien est peut-être ancien ou incomplet.</p>
      <Link className="button primary" to="/"><ArrowLeft size={17} /> Revenir au tableau de bord</Link>
    </div>
  );
}
