// Builds the schedule from JSON after a delay, so only a rendered page has events.
fetch("/events.json")
  .then((response) => response.json())
  .then((events) => setTimeout(() => render(events), 200));

function render(events) {
  const list = document.getElementById("schedule");
  for (const event of events) {
    const item = document.createElement("div");
    item.className = "event";
    item.innerHTML = `<h3>${event.title}</h3><time datetime="${event.start}"></time>`;
    list.appendChild(item);
  }
}
