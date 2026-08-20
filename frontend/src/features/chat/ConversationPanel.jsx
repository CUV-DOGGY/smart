export function ConversationPanel({ items, currentId, onSelect, onNew, onDelete }) {
  return (
    <aside className="conversation-panel">
      <button className="primary full" onClick={onNew}>＋ 新建会话</button>
      <div className="conversation-list">
        {items.length === 0 && <p className="empty-small">还没有会话</p>}
        {items.map((item) => (
          <div className={`conversation-item ${item.conversation_id === currentId ? 'active' : ''}`} key={item.conversation_id}>
            <button onClick={() => onSelect(item.conversation_id)}><strong>{item.title}</strong><small>{new Date(item.updated_at).toLocaleString()}</small></button>
            <button className="icon-button danger" aria-label="删除会话" onClick={() => onDelete(item.conversation_id)}>×</button>
          </div>
        ))}
      </div>
    </aside>
  );
}
