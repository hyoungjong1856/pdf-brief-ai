export default function DocumentStatus({ name, status }) {
  return (
    <section className="card">
      <h2>{name}</h2>
      <p>상태: {status}</p>
    </section>
  );
}
