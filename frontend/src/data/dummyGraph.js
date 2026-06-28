export const dummyGraph = {
  nodes: [
    { id: "song-001", title: "Midnight Aquarium", artist: "Luna Vale", confidence: 0.96 },
    { id: "song-002", title: "Glass Tide", artist: "The Blue Rooms", confidence: 0.94 },
    { id: "song-003", title: "Neon Reef", artist: "Cassette Coral", confidence: 0.92 },
    { id: "song-004", title: "Blue Hour Bloom", artist: "Mika Sol", confidence: 0.9 },
    { id: "song-005", title: "Bubblegum Current", artist: "DJ Starfish", confidence: 0.89 },
    { id: "song-006", title: "Soft Shell Skyline", artist: "Marina Echo", confidence: 0.87 },
    { id: "song-007", title: "Chrome Seahorse", artist: "Pixel Lagoon", confidence: 0.86 },
    { id: "song-008", title: "Pearl Static", artist: "NOVA Koi", confidence: 0.84 },
    { id: "song-009", title: "Afterglow Kelp Forest", artist: "Sunset Modem", confidence: 0.82 },
    { id: "song-010", title: "Last Light Lagoon", artist: "The Memory Divers", confidence: 0.8 }
  ],
  edges: [
    { source: "song-002", target: "song-001", strength: 0.89, label: "similar mood" },
    { source: "song-001", target: "song-003", strength: 0.86, label: "energy lift" },
    { source: "song-003", target: "song-005", strength: 0.91, label: "tempo match" },
    { source: "song-005", target: "song-007", strength: 0.78, label: "retro electronic bridge" },
    { source: "song-007", target: "song-008", strength: 0.74, label: "texture transition" },
    { source: "song-008", target: "song-009", strength: 0.81, label: "cooldown path" },
    { source: "song-009", target: "song-010", strength: 0.85, label: "warm ending" },
    { source: "song-004", target: "song-010", strength: 0.77, label: "emotional close" },
    { source: "song-001", target: "song-004", strength: 0.73, label: "vocal warmth" },
    { source: "song-006", target: "song-004", strength: 0.69, label: "intimate mood" },
    { source: "song-006", target: "song-009", strength: 0.65, label: "soft transition" },
    { source: "song-003", target: "song-007", strength: 0.71, label: "genre bridge" }
  ]
}
