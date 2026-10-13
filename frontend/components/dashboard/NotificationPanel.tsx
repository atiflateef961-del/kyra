import { useEffect, useState } from "react";

import { kyraApi } from "../../lib/api";
import type { Notification } from "../../types/contracts";
import { NeumorphicButton } from "../ui/NeumorphicButton";

export function NotificationPanel() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  async function loadNotifications() {
    setLoading(true);
    try {
      setNotifications(await kyraApi.listNotifications());
      setMessage(null);
    } catch {
      setMessage("Notification inbox is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadNotifications();
  }, []);

  async function dismissNotification(notificationId: string) {
    try {
      await kyraApi.dismissNotification(notificationId);
      setNotifications((current) => current.filter((item) => item.notification_id !== notificationId));
    } catch {
      setMessage("The notification could not be dismissed.");
    }
  }

  async function markAsRead(notificationId: string) {
    try {
      await kyraApi.markNotificationRead(notificationId);
      setNotifications((current) => current.map((item) => item.notification_id === notificationId ? { ...item, read: true, updated_at: new Date().toISOString() } : item));
    } catch {
      setMessage("The notification could not be marked as read.");
    }
  }

  return (
    <section className="kyra-notification-panel" aria-labelledby="notification-panel-title">
      <div className="kyra-dashboard__panel-heading">
        <div>
          <p className="kyra-dashboard__eyebrow">Inbox</p>
          <h2 id="notification-panel-title">Notifications</h2>
        </div>
        <span className="kyra-dashboard__state">{loading ? "Loading" : `${notifications.length} active`}</span>
      </div>

      {message ? <p className="kyra-device-panel__message" role="status">{message}</p> : null}
      {notifications.length === 0 && !loading ? <p className="kyra-dashboard__empty">No active notifications for this account.</p> : null}

      <div className="kyra-notification-panel__list">
        {notifications.map((notification) => (
          <div className={`kyra-notification-panel__row kyra-notification-panel__row--${notification.severity}`} key={notification.notification_id}>
            <div>
              <div className="kyra-notification-panel__meta">
                <strong>{notification.title}</strong>
                <span>{notification.severity}</span>
              </div>
              <p>{notification.message}</p>
              <small>{notification.read ? "Read" : "Unread"}</small>
            </div>
            <div className="kyra-notification-panel__actions">
              {!notification.read ? <NeumorphicButton onClick={() => void markAsRead(notification.notification_id)} size="sm" tone="primary">Mark read</NeumorphicButton> : null}
              <NeumorphicButton onClick={() => void dismissNotification(notification.notification_id)} size="sm" tone="danger">Dismiss</NeumorphicButton>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
