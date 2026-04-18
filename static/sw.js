self.addEventListener('push', function(event) {
    const data = event.data.json();
    self.registration.showNotification(data.title, {
        body: data.body,
        icon: '/static/img/logo.png',
        badge: '/static/img/logo.png',
        data: { url: data.url || '/' }
    });
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    event.waitUntil(clients.openWindow(event.notification.data.url));
});
